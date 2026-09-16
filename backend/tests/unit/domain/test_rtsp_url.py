import pytest

from app.domain.exceptions import DomainValidationException
from app.domain.services.rtsp_url import redact_rtsp_uri, validate_rtsp_url


def test_validate_accepts_lan_rtsp() -> None:
    assert validate_rtsp_url("rtsp://192.168.1.10/cam") == "rtsp://192.168.1.10/cam"


def test_validate_rejects_non_rtsp() -> None:
    with pytest.raises(DomainValidationException):
        validate_rtsp_url("http://example.com/x")


def test_validate_blocks_metadata_ip() -> None:
    with pytest.raises(DomainValidationException):
        validate_rtsp_url("rtsp://169.254.169.254/latest/meta-data/")


def test_redact_strips_userinfo() -> None:
    assert (
        redact_rtsp_uri("rtsp://user:s3cret@cam.local/stream")
        == "rtsp://***@cam.local/stream"
    )


def test_redact_leaves_plain_uri() -> None:
    assert redact_rtsp_uri("rtsp://cam.local/stream") == "rtsp://cam.local/stream"
