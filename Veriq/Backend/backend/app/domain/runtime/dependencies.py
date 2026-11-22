"""Where the HTTP fault proxy forwards to.

The proxy is a real hop between the application and its test dependency
(``Application -> proxy -> dependency``). It therefore needs to know the
upstream URL before a run can be prepared; the same answer is required at
planning time, so a plan cannot be approved with a case that could never be
executed.

Resolution order (first match wins), mirroring the documented scenario
configuration:

1. ``scenario_config.dependency_url`` — explicit per-scenario configuration.
2. The application runtime profile's ``http.upstream_url`` — a fixed upstream.
3. The test input value of the profile's ``http.input_field`` — the value the
   runner rewrites to the proxy.
4. The first absolute http(s) URL found anywhere in the contract safe input.

Everything here is pure: no I/O, no ORM, no settings.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

HTTP_PROXY_SCENARIOS: tuple[str, ...] = (
    "dependency_timeout",
    "successful_operation_lost_response",
)

DEPENDENCY_URL_MISSING = "HTTP_DEPENDENCY_URL_MISSING"
DEPENDENCY_URL_INVALID = "HTTP_DEPENDENCY_URL_INVALID"
PROXY_NOT_ROUTED = "HTTP_PROXY_NOT_ROUTED"

DEPENDENCY_URL_FIELD = "scenario_config.dependency_url"

_MISSING_MESSAGE = (
    "The HTTP fault proxy needs the upstream dependency it forwards to. Set "
    "'scenario_config.dependency_url' on the task's scenario configuration (the "
    "'Upstream dependency URL' field on the task's reliability page), or an http "
    "runtime profile 'upstream_url'/'input_field', or include an absolute "
    "http(s) URL in the contract safe input."
)


def is_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    try:
        parsed = urlsplit(text)
    except (TypeError, ValueError):
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def proxy_url(original: str, proxy_origin: str) -> str:
    """Replace only the scheme/host of a dependency URL with the proxy."""
    suffix = ""
    if is_http_url(original):
        parts = urlsplit(original.strip())
        suffix = parts.path or ""
        if parts.query:
            suffix += "?" + parts.query
    return f"{proxy_origin}{suffix}"


def rewrite_http_urls(value: Any, proxy_origin: str) -> Any:
    if isinstance(value, dict):
        return {
            key: rewrite_http_urls(child, proxy_origin) for key, child in value.items()
        }
    if isinstance(value, list):
        return [rewrite_http_urls(child, proxy_origin) for child in value]
    if isinstance(value, str) and is_http_url(value):
        return proxy_url(value, proxy_origin)
    return value


def find_http_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for child in value.values():
            found = find_http_url(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_http_url(child)
            if found is not None:
                return found
    elif isinstance(value, str) and is_http_url(value):
        return value.strip()
    return None


def _http_profile(profile: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(profile, Mapping):
        return {}
    value = profile.get("http")
    return value if isinstance(value, Mapping) else {}


def dependency_upstream(
    configuration: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
) -> str | None:
    configuration = configuration or {}
    scenario_config = configuration.get("scenario_config")
    if isinstance(scenario_config, Mapping):
        configured_url = scenario_config.get("dependency_url")
        if is_http_url(configured_url):
            return str(configured_url).strip()

    http_profile = _http_profile(profile)
    upstream = http_profile.get("upstream_url")
    if is_http_url(upstream):
        return str(upstream).strip()

    test_input = configuration.get("test_input")
    field = http_profile.get("input_field")
    if isinstance(test_input, Mapping) and field:
        value = test_input.get(field)
        if is_http_url(value):
            return str(value).strip()

    return find_http_url(test_input)


def proxy_routes_requests(
    configuration: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
) -> bool:
    """Whether the worker can actually be pointed at the proxy.

    The proxy only sees traffic when the runner can hand the application the
    proxy origin: a rewritten test-input field, a rewritten environment
    variable, or an absolute URL in the test input that is rewritten in place.
    """
    configuration = configuration or {}
    http_profile = _http_profile(profile)
    if http_profile.get("url_env"):
        return True
    test_input = configuration.get("test_input")
    field = http_profile.get("input_field")
    if isinstance(test_input, Mapping) and field and is_http_url(test_input.get(field)):
        return True
    return find_http_url(test_input) is not None


def dependency_issue(
    configuration: Mapping[str, Any] | None,
    profile: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """A blocking issue when the configured upstream cannot be used, else None."""
    configuration = configuration or {}
    scenario_config = configuration.get("scenario_config")
    configured = (
        scenario_config.get("dependency_url")
        if isinstance(scenario_config, Mapping)
        else None
    )
    if configured is not None and not is_http_url(configured):
        return {
            "code": DEPENDENCY_URL_INVALID,
            "severity": "error",
            "message": (
                "'scenario_config.dependency_url' must be an absolute http(s) URL, "
                f"for example https://sandbox.example/quote (received {configured!r})."
            ),
            "field": DEPENDENCY_URL_FIELD,
        }
    if dependency_upstream(configuration, profile) is not None:
        return None
    return {
        "code": DEPENDENCY_URL_MISSING,
        "severity": "error",
        "message": _MISSING_MESSAGE,
        "field": DEPENDENCY_URL_FIELD,
    }


__all__ = [
    "DEPENDENCY_URL_FIELD",
    "DEPENDENCY_URL_INVALID",
    "DEPENDENCY_URL_MISSING",
    "HTTP_PROXY_SCENARIOS",
    "PROXY_NOT_ROUTED",
    "dependency_issue",
    "dependency_upstream",
    "find_http_url",
    "is_http_url",
    "proxy_routes_requests",
    "proxy_url",
    "rewrite_http_urls",
]
