"""Decide what an upload really is from its bytes, never from its name or MIME type."""

import io
import zipfile

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc / .xls
DOCX_MAIN = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
MACRO = b"macroenabled"
MAX_CONTENT_TYPES = 256 * 1024


class ImportFailure(Exception):
    """A user-facing import error: code + message (never contains file content)."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


UNSUPPORTED = (
    "Upload a PDF or a Word .docx file. Old .doc files and macro-enabled documents "
    "aren't supported: open it in Word and save as .docx."
)


def _content_types(data: bytes) -> bytes | None:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        info = z.getinfo("[Content_Types].xml")
    except (zipfile.BadZipFile, KeyError, ValueError):
        return None
    if info.file_size > MAX_CONTENT_TYPES:
        return None
    with z.open(info) as f:
        return f.read(MAX_CONTENT_TYPES + 1)[:MAX_CONTENT_TYPES]


def sniff(data: bytes) -> str:
    """'pdf', 'docx' or 'zip'; anything else raises ImportFailure(UNSUPPORTED_FILE)."""
    if data.startswith(PDF_MAGIC):
        return "pdf"
    if data.startswith(ZIP_MAGIC):
        ct = _content_types(data)
        if ct is None:
            return "zip"
        low = ct.lower()
        if MACRO in low:
            raise ImportFailure("UNSUPPORTED_FILE", UNSUPPORTED, 415)
        if DOCX_MAIN in ct:
            return "docx"
        return "zip"  # some other Office file: not a resume, not a LinkedIn export
    raise ImportFailure("UNSUPPORTED_FILE", UNSUPPORTED, 415)


def check_pdf(data: bytes) -> None:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
    except (PdfReadError, ValueError, OSError):
        raise ImportFailure("UNSUPPORTED_FILE", "That PDF can't be read.", 415) from None
    if encrypted:
        raise ImportFailure(
            "ENCRYPTED_PDF",
            "That PDF is password-protected. Save a copy without a password and upload it.",
            415,
        )
