import pytest

from mebot.widget.origins import MAX_ORIGINS, OriginError, matches, normalise, validate_list


@pytest.mark.parametrize(
    "raw,want",
    [
        ("https://Shivansh.DEV", "https://shivansh.dev"),
        ("https://shivansh.dev/", "https://shivansh.dev"),
        ("https://shivansh.dev:443", "https://shivansh.dev"),
        ("https://shivansh.dev:8443", "https://shivansh.dev:8443"),
        ("http://localhost:3000", "http://localhost:3000"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("http://localhost:80", "http://localhost"),
        ("https://*.Example.com", "https://*.example.com"),
        ("  https://a.example.com  ", "https://a.example.com"),
    ],
)
def test_normalise_ok(raw, want):
    assert normalise(raw) == want


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "shivansh.dev",
        "http://shivansh.dev",
        "ftp://shivansh.dev",
        "https://shivansh.dev/path",
        "https://shivansh.dev?q=1",
        "https://shivansh.dev#x",
        "https://user@shivansh.dev",
        "https://*.*.example.com",
        "https://a.*.example.com",
        "https://*example.com",
        "https://*.com",
        "https://shivansh.dev:99999",
        "https://bad host.com",
        "https://shivansh.dev; script-src *",
        "javascript:alert(1)",
        "*",
    ],
)
def test_normalise_rejects(raw):
    with pytest.raises(OriginError):
        normalise(raw)


def test_validate_list_dedupes_and_limits():
    assert validate_list(["https://a.com", "https://A.com/"]) == ["https://a.com"]
    with pytest.raises(OriginError):
        validate_list([f"https://s{i}.com" for i in range(MAX_ORIGINS + 1)])


def test_wildcard_matching():
    allowed = ["https://*.example.com", "https://shivansh.dev"]
    assert matches("https://a.example.com", allowed)
    assert not matches("https://example.com", allowed)
    assert not matches("https://a.b.example.com", allowed)
    assert not matches("http://a.example.com", allowed)
    assert matches("https://shivansh.dev", allowed)
    assert matches("https://SHIVANSH.dev:443", allowed)
    assert not matches("https://evil.dev", allowed)
    assert not matches("not a url", allowed)
    assert not matches(None, allowed)
