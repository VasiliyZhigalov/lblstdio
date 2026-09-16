from app.domain.services.slugify import latin_slug, trained_model_name


def test_latin_slug_transliterates_cyrillic() -> None:
    assert latin_slug("Кузов") == "kuzov"
    assert latin_slug("Левая камера") == "levaya_kamera"
    assert latin_slug("ABC-123") == "abc_123"


def test_latin_slug_handles_mixed_and_empty() -> None:
    assert latin_slug("Project_Alpha") == "project_alpha"
    assert latin_slug("!!!") == "model"
    assert latin_slug("") == "model"


def test_trained_model_name() -> None:
    assert trained_model_name("Кузов", 1) == "kuzov_v1"
    assert trained_model_name("Left Cam", 3) == "left_cam_v3"
