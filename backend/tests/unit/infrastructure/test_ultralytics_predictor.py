from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.infrastructure.ml.ultralytics_predictor import UltralyticsPredictor


def test_predictor_matches_resolved_paths_only_not_basename(tmp_path, monkeypatch) -> None:
    img_a = tmp_path / "dir_a" / "frame.jpg"
    img_b = tmp_path / "dir_b" / "frame.jpg"
    img_a.parent.mkdir()
    img_b.parent.mkdir()
    img_a.write_bytes(b"a")
    img_b.write_bytes(b"b")

    boxes = SimpleNamespace(
        xywhn=MagicMock(**{"cpu.return_value.tolist.return_value": [[0.5, 0.5, 0.2, 0.2]]}),
        conf=MagicMock(**{"cpu.return_value.tolist.return_value": [0.9]}),
        cls=MagicMock(**{"cpu.return_value.tolist.return_value": [0]}),
    )
    # len(boxes) used in predictor
    boxes.__len__ = lambda self: 1  # type: ignore[method-assign]

    class _Boxes:
        def __init__(self) -> None:
            self.xywhn = MagicMock()
            self.xywhn.cpu.return_value.tolist.return_value = [[0.5, 0.5, 0.2, 0.2]]
            self.conf = MagicMock()
            self.conf.cpu.return_value.tolist.return_value = [0.9]
            self.cls = MagicMock()
            self.cls.cpu.return_value.tolist.return_value = [0]

        def __len__(self) -> int:
            return 1

    result = SimpleNamespace(path=str(img_a), boxes=_Boxes())

    class _YOLO:
        def __init__(self, _weights: str) -> None:
            pass

        def predict(self, source, conf, verbose=False):
            return [result]

    ultralytics = MagicMock(YOLO=_YOLO)
    monkeypatch.setitem(__import__("sys").modules, "ultralytics", ultralytics)

    out = UltralyticsPredictor().predict("w.pt", [str(img_a), str(img_b)], 0.5)
    assert len(out[str(img_a)]) == 1
    assert out[str(img_b)] == []


def test_predictor_does_not_attach_unmatched_paths(tmp_path, monkeypatch) -> None:
    img = tmp_path / "known.jpg"
    img.write_bytes(b"x")
    other = tmp_path / "other.jpg"

    class _Boxes:
        def __init__(self) -> None:
            self.xywhn = MagicMock()
            self.xywhn.cpu.return_value.tolist.return_value = [[0.5, 0.5, 0.1, 0.1]]
            self.conf = MagicMock()
            self.conf.cpu.return_value.tolist.return_value = [0.8]
            self.cls = MagicMock()
            self.cls.cpu.return_value.tolist.return_value = [0]

        def __len__(self) -> int:
            return 1

    result = SimpleNamespace(path=str(other), boxes=_Boxes())

    class _YOLO:
        def __init__(self, _weights: str) -> None:
            pass

        def predict(self, source, conf, verbose=False):
            return [result]

    monkeypatch.setitem(__import__("sys").modules, "ultralytics", MagicMock(YOLO=_YOLO))

    out = UltralyticsPredictor().predict("w.pt", [str(img)], 0.5)
    assert out[str(img)] == []
