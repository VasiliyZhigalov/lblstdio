"""Native folder picker.

PowerShell and FolderBrowserDialog are not used. Starting a shell, then the
legacy browse dialog, blocks for a long time before any window is shown.
"""

from __future__ import annotations

import sys
import uuid
from ctypes import (
    HRESULT,
    POINTER,
    Structure,
    WINFUNCTYPE,
    byref,
    c_ubyte,
    c_uint16,
    c_uint32,
    c_ulong,
    c_void_p,
    c_wchar_p,
    cast,
)
from pathlib import Path

_CANCELLED = 0x800704C7
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_FOS_FORCEFILESYSTEM = 0x40
_FOS_NOCHANGEDIR = 0x8
_FOS_PATHMUSTEXIST = 0x800
_FOS_PICKFOLDERS = 0x20
_SIGDN_FILESYSPATH = 0x80058000
_TITLE = "Выберите папку с изображениями"
_PICK_FAILED = "Не удалось открыть окно выбора папки"


class _GUID(Structure):
    _fields_ = [
        ("Data1", c_uint32),
        ("Data2", c_uint16),
        ("Data3", c_uint16),
        ("Data4", c_ubyte * 8),
    ]


def dialog_result(hresult: int, path: str | None) -> str | None:
    code = int(hresult) & 0xFFFFFFFF
    if code == _CANCELLED:
        return None
    if code != 0:
        raise RuntimeError(_PICK_FAILED)
    text = (path or "").strip()
    return text or None


def ask_image_folder(initial: str | None = None) -> str | None:
    return show_folder_dialog(initial)


def show_folder_dialog(initial: str | None = None) -> str | None:
    if sys.platform != "win32":
        raise RuntimeError(_PICK_FAILED)

    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    _bind_com(ole32, shell32, user32, wintypes)

    init_code = int(ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)) & 0xFFFFFFFF
    if init_code not in (0, 1):
        raise RuntimeError(_PICK_FAILED)
    should_uninit = init_code == 0

    dialog = c_void_p()
    try:
        _create_dialog(ole32, dialog)
        vtbl = _vtable(dialog)
        options = (
            _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST | _FOS_NOCHANGEDIR
        )
        _check(_invoke(vtbl, 9, HRESULT, ctypes.c_uint)(dialog, options))
        _check(_invoke(vtbl, 17, HRESULT, c_wchar_p)(dialog, _TITLE))
        _set_initial_folder(shell32, dialog, vtbl, initial)

        owner = user32.GetForegroundWindow()
        shown = _invoke(vtbl, 3, HRESULT, wintypes.HWND)(dialog, owner)
        path = _selected_path(ole32, dialog, vtbl) if int(shown) & 0xFFFFFFFF == 0 else None
        return dialog_result(shown, path)
    finally:
        if dialog.value:
            _release(dialog)
        if should_uninit:
            ole32.CoUninitialize()


def _bind_com(ole32, shell32, user32, wintypes) -> None:
    import ctypes

    ole32.CoInitializeEx.argtypes = [c_void_p, ctypes.c_uint]
    ole32.CoInitializeEx.restype = HRESULT
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoTaskMemFree.argtypes = [c_void_p]
    ole32.CoTaskMemFree.restype = None
    ole32.CoCreateInstance.argtypes = [
        POINTER(_GUID),
        c_void_p,
        ctypes.c_uint,
        POINTER(_GUID),
        POINTER(c_void_p),
    ]
    ole32.CoCreateInstance.restype = HRESULT
    shell32.SHCreateItemFromParsingName.argtypes = [
        c_wchar_p,
        c_void_p,
        POINTER(_GUID),
        POINTER(c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND


def _create_dialog(ole32, dialog: c_void_p) -> None:
    clsid = _guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")
    iid = _guid("D57C7288-D4AD-4768-BE02-9D969532D960")
    hr = ole32.CoCreateInstance(
        byref(clsid), None, _CLSCTX_INPROC_SERVER, byref(iid), byref(dialog)
    )
    if int(hr) & 0xFFFFFFFF != 0 or not dialog.value:
        raise RuntimeError(_PICK_FAILED)


def _set_initial_folder(shell32, dialog: c_void_p, vtbl, initial: str | None) -> None:
    if not initial or not Path(initial).is_dir():
        return
    iid = _guid("43826D1E-E718-42EE-BC55-A1E261C37BFE")
    item = c_void_p()
    hr = shell32.SHCreateItemFromParsingName(initial, None, byref(iid), byref(item))
    if int(hr) & 0xFFFFFFFF != 0 or not item.value:
        return
    try:
        _check(_invoke(vtbl, 12, HRESULT, c_void_p)(dialog, item))
    finally:
        _release(item)


def _selected_path(ole32, dialog: c_void_p, vtbl) -> str | None:
    item = c_void_p()
    hr = _invoke(vtbl, 20, HRESULT, POINTER(c_void_p))(dialog, byref(item))
    if int(hr) & 0xFFFFFFFF != 0 or not item.value:
        raise RuntimeError(_PICK_FAILED)
    try:
        name = c_wchar_p()
        hr = _invoke(_vtable(item), 5, HRESULT, c_ulong, POINTER(c_wchar_p))(
            item, _SIGDN_FILESYSPATH, byref(name)
        )
        _check(hr)
        path = name.value
        if name:
            ole32.CoTaskMemFree(cast(name, c_void_p))
        return path
    finally:
        _release(item)


def _invoke(vtbl, index: int, restype, *argtypes):
    prototype = WINFUNCTYPE(restype, c_void_p, *argtypes)
    return prototype(vtbl[index])


def _vtable(com: c_void_p):
    return cast(com, POINTER(POINTER(c_void_p)))[0]


def _release(com: c_void_p) -> None:
    if com.value:
        _invoke(_vtable(com), 2, c_ulong)(com)


def _check(hresult: int) -> None:
    if int(hresult) & 0xFFFFFFFF != 0:
        raise RuntimeError(_PICK_FAILED)


def _guid(value: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
