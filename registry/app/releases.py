"""``releases.json``: maintained by hand, hot-reloaded when the file changes."""

import json
import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

log = logging.getLogger("registry.releases")


class Advisory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(max_length=64)
    severity: str = Field(default="medium", max_length=16)
    affected: str = Field(max_length=64)  # e.g. "<0.10.1"
    title: str = Field(max_length=200)
    url: str | None = Field(default=None, max_length=300)


class Releases(BaseModel):
    model_config = ConfigDict(extra="ignore")

    latest: str = Field(max_length=40)
    min_supported: str | None = Field(default=None, max_length=40)
    released_at: str | None = Field(default=None, max_length=40)
    notes_url: str | None = Field(default=None, max_length=300)
    advisories: list[Advisory] = Field(default_factory=list, max_length=50)


class ReleasesFile:
    def __init__(self, path: Path):
        self.path = path
        # (mtime_ns, size): two quick edits can share an mtime on coarse filesystem clocks.
        self._stamp: tuple[int, int] | None = None
        self._value = Releases(latest="0.0.0")

    def get(self) -> Releases:
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            return self._value
        if stamp != self._stamp:
            try:
                self._value = Releases.model_validate(json.loads(self.path.read_text("utf-8")))
            except (OSError, ValueError, ValidationError):
                # Keep serving the last good copy; a half-written edit must not break clients.
                log.warning("releases.json is invalid; keeping the previous version")
            self._stamp = stamp
        return self._value
