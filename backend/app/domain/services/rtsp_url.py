"""RTSP URL validation and redaction for stream sources."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit

from app.domain.exceptions import DomainValidationException

_BLOCKED_HOSTS = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)
_BLOCKED_IPS = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),
    }
)


def redact_rtsp_uri(uri: str) -> str:
    """Hide userinfo in RTSP URIs for API responses."""
    parts = urlsplit(uri)
    if parts.scheme.lower() != "rtsp" or "@" not in parts.netloc:
        return uri
    _, hostport = parts.netloc.rsplit("@", 1)
    return urlunsplit(
        (parts.scheme, f"***@{hostport}", parts.path, parts.query, parts.fragment)
    )


def validate_rtsp_url(rtsp_url: str) -> str:
    """Normalize and validate an RTSP URL for trusted-operator capture.

    Blocks cloud-metadata endpoints. Private LAN cameras remain allowed
    (typical deployment). Credentials stay in storage; callers should redact
    on read via :func:`redact_rtsp_uri`.
    """
    url = rtsp_url.strip()
    if not url.lower().startswith("rtsp://"):
        raise DomainValidationException("rtsp_url must start with rtsp://")
    parts = urlsplit(url)
    if parts.scheme.lower() != "rtsp":
        raise DomainValidationException("rtsp_url must use rtsp:// scheme")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise DomainValidationException("rtsp_url must include a host")
    if host in _BLOCKED_HOSTS:
        raise DomainValidationException("rtsp_url host is not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and ip in _BLOCKED_IPS:
        raise DomainValidationException("rtsp_url host is not allowed")
    if re.search(r"[\s<>\"']", url):
        raise DomainValidationException("rtsp_url contains invalid characters")
    return url
