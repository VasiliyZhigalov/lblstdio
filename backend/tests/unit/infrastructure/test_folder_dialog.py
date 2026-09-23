import subprocess
import sys

import pytest

from app.infrastructure.system.folder_dialog import ask_image_folder, dialog_result


def test_dialog_result_returns_selected_path() -> None:
    assert dialog_result(0, "C:\\Папка\\кадры") == "C:\\Папка\\кадры"


def test_dialog_result_cancel_returns_none() -> None:
    assert dialog_result(0x800704C7, "C:\\ignored") is None
    assert dialog_result(-2147023673, "C:\\ignored") is None


def test_dialog_result_failure_raises() -> None:
    with pytest.raises(RuntimeError, match="Не удалось открыть окно выбора папки"):
        dialog_result(0x80004005, None)


def test_ask_image_folder_uses_inprocess_dialog_without_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args, **_kwargs):
        raise AssertionError("folder picker must not spawn a process")

    monkeypatch.setattr(subprocess, "run", explode)
    monkeypatch.setattr(
        "app.infrastructure.system.folder_dialog.show_folder_dialog",
        lambda initial=None: "C:\\Папка\\кадры" if initial == "C:\\start" else None,
    )

    assert ask_image_folder("C:\\start") == "C:\\Папка\\кадры"
    assert ask_image_folder() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 folder dialog")
def test_folder_dialog_object_can_be_created_without_showing() -> None:
    import ctypes
    from ctypes import wintypes

    from app.infrastructure.system import folder_dialog as dialog

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dialog._bind_com(ole32, shell32, user32, wintypes)
    init_code = int(ole32.CoInitializeEx(None, 0x2)) & 0xFFFFFFFF
    assert init_code in (0, 1)
    com = ctypes.c_void_p()
    try:
        dialog._create_dialog(ole32, com)
        vtbl = dialog._vtable(com)
        dialog._check(
            dialog._invoke(vtbl, 9, dialog.HRESULT, ctypes.c_uint)(com, 0x868)
        )
        dialog._check(
            dialog._invoke(vtbl, 17, dialog.HRESULT, dialog.c_wchar_p)(com, "probe")
        )
    finally:
        if com.value:
            dialog._release(com)
        if init_code == 0:
            ole32.CoUninitialize()
