from pathlib import Path

from app.infrastructure.ml.device import (
    describe_training_device,
    probe_training_device,
    resolve_training_device,
)
from app.domain.exceptions import DomainValidationException
import pytest


def test_resolve_explicit_cpu() -> None:
    assert resolve_training_device("cpu") == "cpu"


def test_resolve_cuda_aliases() -> None:
    assert resolve_training_device("cuda") == "0"
    assert resolve_training_device("cuda:0") == "0"
    assert resolve_training_device("gpu") == "0"


def test_resolve_rejects_arbitrary_device() -> None:
    with pytest.raises(DomainValidationException):
        resolve_training_device("rm -rf /")
    with pytest.raises(DomainValidationException):
        resolve_training_device("mps")


def test_describe_training_device() -> None:
    assert describe_training_device("cpu") == "CPU"
    assert describe_training_device("0") == "GPU (CUDA:0)"


def test_probe_training_device_shape() -> None:
    payload = probe_training_device("auto")
    assert payload["device"] in {"cpu", "0"}
    assert payload["backend"] in {"cpu", "gpu"}
    assert payload["label"]
