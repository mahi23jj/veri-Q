import pytest

from veriq import VeriQConfig
from veriq.exceptions import VeriQConfigError

from .conftest import API_KEY


def test_valid_configuration_defaults():
    config = VeriQConfig("http://localhost:8000", API_KEY)
    assert config.base_url == "http://localhost:8000"
    assert config.api_url == "http://localhost:8000/api/v1"
    assert config.timeout == 10.0


@pytest.mark.parametrize(
    ("given", "expected_base"),
    [
        ("http://localhost:8000/", "http://localhost:8000"),
        ("http://localhost:8000/api/v1", "http://localhost:8000"),
        ("http://localhost:8000/api/v1/", "http://localhost:8000"),
        ("  https://veriq.example.com  ", "https://veriq.example.com"),
        ("https://example.com/prefix/", "https://example.com/prefix"),
        ("https://example.com/prefix/api/v1", "https://example.com/prefix"),
    ],
)
def test_url_normalization(given, expected_base):
    config = VeriQConfig(given, API_KEY)
    assert config.base_url == expected_base
    assert config.api_url == f"{expected_base}/api/v1"


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "   ",
        "localhost:8000",
        "ftp://localhost:8000",
        "http://",
        "http://user:password@localhost:8000",
        "http://user@localhost:8000",
    ],
)
def test_invalid_api_urls_rejected(bad_url):
    with pytest.raises(VeriQConfigError):
        VeriQConfig(bad_url, API_KEY)


@pytest.mark.parametrize("bad_key", ["", "   ", "key with spaces", "x" * 513])
def test_invalid_api_keys_rejected(bad_key):
    with pytest.raises(VeriQConfigError):
        VeriQConfig("http://localhost:8000", bad_key)


@pytest.mark.parametrize("bad_timeout", [0, -1, 0.0, 121, "soon", None])
def test_invalid_timeouts_rejected(bad_timeout):
    with pytest.raises(VeriQConfigError):
        VeriQConfig("http://localhost:8000", API_KEY, timeout=bad_timeout)


def test_timeout_is_accepted_within_bounds():
    assert VeriQConfig("http://localhost:8000", API_KEY, timeout=0.5).timeout == 0.5
    assert VeriQConfig("http://localhost:8000", API_KEY, timeout="5").timeout == 5.0


def test_repr_and_redacted_output_never_contain_the_api_key():
    config = VeriQConfig("http://localhost:8000", API_KEY)
    for text in (repr(config), str(config), str(config.redacted())):
        assert API_KEY not in text
    assert config.redacted()["api_key"] == "***"
