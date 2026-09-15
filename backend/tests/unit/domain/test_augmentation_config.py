from app.domain.entities.dataset_version import AugmentationConfig
from app.infrastructure.db.mappers import dict_to_augmentation, augmentation_to_dict


def test_default_augmentation_is_roboflow_core_640() -> None:
    config = AugmentationConfig()
    assert config.resize_width == 640
    assert config.resize_height == 640
    assert config.horizontal_flip is True
    assert config.vertical_flip is False
    assert config.rotate is True
    assert config.shear is True
    assert config.hue_saturation is True
    assert config.brightness_contrast is True
    assert config.blur is False
    assert config.noise is False
    assert config.grayscale is False
    assert config.cutout is False


def test_dict_to_augmentation_maps_legacy_shift_scale_rotate() -> None:
    config = dict_to_augmentation(
        {
            "resize_width": 640,
            "resize_height": 640,
            "horizontal_flip": True,
            "brightness_contrast": True,
            "blur": False,
            "shift_scale_rotate": True,
            "multiplier": 3,
        }
    )
    assert config.rotate is True
    assert config.shear is True
    assert config.shift_scale_rotate is False


def test_augmentation_roundtrip_preserves_new_flags() -> None:
    original = AugmentationConfig(
        vertical_flip=True,
        noise=True,
        grayscale=True,
        cutout=True,
        rotate=False,
        shear=False,
    )
    restored = dict_to_augmentation(augmentation_to_dict(original))
    assert restored.vertical_flip is True
    assert restored.noise is True
    assert restored.grayscale is True
    assert restored.cutout is True
    assert restored.rotate is False
    assert restored.shear is False
