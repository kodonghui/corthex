"""Read Windows app execution aliases without launching their targets."""

import os
import re
import struct
from pathlib import PureWindowsPath


APP_EXEC_LINK = 0x8000001B
_WSL_NAME = "MicrosoftCorporationII.WindowsSubsystemForLinux"
_WSL_FAMILY = _WSL_NAME + "_8wekyb3d8bbwe"
_WSL_PACKAGE = re.compile(re.escape(_WSL_NAME) + r"_\d+(?:\.\d+){3}_(?:x64|arm64)__8wekyb3d8bbwe", re.IGNORECASE)


def decode(data):
    """Return the identity and target from a version 3 AppExecLink buffer."""
    if len(data) < 12:
        return None
    tag, length, _, version = struct.unpack_from("<IHHI", data)
    if tag != APP_EXEC_LINK or length != len(data) - 8 or version != 3:
        return None
    try:
        fields = data[12:].decode("utf-16-le").split("\0")
    except UnicodeError:
        return None
    if len(fields) != 5 or fields[-1] or not all(fields[:4]):
        return None
    family, app, target, _ = fields[:4]
    return {"tag": f"0x{tag:08x}", "version": version, "family": family, "app": app, "target": target}


def read(path):
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    ioctl = kernel.DeviceIoControl
    ioctl.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                      wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
    ioctl.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = (wintypes.HANDLE,)
    close.restype = wintypes.BOOL

    # OPEN_EXISTING, share read/write/delete, open the reparse point itself.
    handle = create(str(path), 0, 7, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        return None
    try:
        buffer = ctypes.create_string_buffer(16 * 1024)
        returned = wintypes.DWORD()
        # FSCTL_GET_REPARSE_POINT.
        if not ioctl(handle, 0x000900A8, None, 0, buffer, len(buffer), ctypes.byref(returned), None):
            return None
        return decode(buffer.raw[:returned.value])
    finally:
        close(handle)


def is_wsl(metadata):
    if not metadata or (metadata.get("tag"), metadata.get("version")) != ("0x8000001b", 3):
        return False
    target = PureWindowsPath(metadata["target"])
    return (metadata["family"].casefold() == _WSL_FAMILY.casefold() and
            metadata["app"].casefold() == (_WSL_FAMILY + "!wsl").casefold() and
            target.is_absolute() and target.name.casefold() == "wsl.exe" and
            target.parent.parent.name.casefold() == "windowsapps" and
            _WSL_PACKAGE.fullmatch(target.parent.name) is not None)
