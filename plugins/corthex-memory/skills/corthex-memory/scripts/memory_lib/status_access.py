"""Non-mutating root-directory creation-rights metadata; never a write promise."""
import ctypes
import os


def _windows(folder):
    from ctypes import wintypes as w
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    dword, handle = ctypes.POINTER(w.DWORD), ctypes.POINTER(w.HANDLE)
    class Mapping(ctypes.Structure):
        _fields_ = [(name, w.DWORD) for name in ("read", "write", "execute", "all")]
    class Luid(ctypes.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.LONG)]
    class Privilege(ctypes.Structure):
        _fields_ = [("luid", Luid), ("attributes", w.DWORD)]
    class Privileges(ctypes.Structure):
        _fields_ = [("count", w.DWORD), ("control", w.DWORD), ("values", Privilege * 1)]
    signatures = ((adv.GetFileSecurityW, [w.LPCWSTR, w.DWORD, pointer, w.DWORD, dword]),
                  (adv.OpenProcessToken, [w.HANDLE, w.DWORD, handle]),
                  (adv.DuplicateToken, [w.HANDLE, ctypes.c_int, handle]),
                  (adv.AccessCheck, [pointer, w.HANDLE, w.DWORD, ctypes.POINTER(Mapping),
                                     pointer, dword, dword, ctypes.POINTER(w.BOOL)]),
                  (kernel.CloseHandle, [w.HANDLE]))
    for function, arguments in signatures:
        function.argtypes, function.restype = arguments, w.BOOL
    kernel.GetCurrentProcess.argtypes, kernel.GetCurrentProcess.restype = [], w.HANDLE
    needed = w.DWORD()
    ctypes.set_last_error(0)
    adv.GetFileSecurityW(str(folder), 7, None, 0, ctypes.byref(needed))
    if ctypes.get_last_error() != 122 or not needed.value:
        return False
    descriptor = ctypes.create_string_buffer(needed.value)
    if not adv.GetFileSecurityW(str(folder), 7, descriptor, len(descriptor), ctypes.byref(needed)):
        return False
    token, duplicate = w.HANDLE(), w.HANDLE()
    try:
        if not adv.OpenProcessToken(kernel.GetCurrentProcess(), 10, ctypes.byref(token)):
            return False
        if not adv.DuplicateToken(token, 2, ctypes.byref(duplicate)):
            return False
        mapping = Mapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
        privilege_bytes = ctypes.sizeof(Privileges)
        for _ in range(2):
            privileges = ctypes.create_string_buffer(privilege_bytes)
            size, granted, allowed = w.DWORD(privilege_bytes), w.DWORD(), w.BOOL()
            passed = adv.AccessCheck(descriptor, duplicate, 6, ctypes.byref(mapping), privileges,
                                     ctypes.byref(size), ctypes.byref(granted), ctypes.byref(allowed))
            if passed:
                return bool(allowed.value and granted.value & 6 == 6)
            if ctypes.get_last_error() != 122 or size.value <= privilege_bytes:
                return False
            privilege_bytes = size.value
        return False
    finally:
        if duplicate:
            kernel.CloseHandle(duplicate)
        if token:
            kernel.CloseHandle(token)


def writable(folder):
    """Current root creation rights only; no probe/ACL change/elevation.

    AccessCheck uses the process's own duplicated token. Failed queries yield
    False; child-file ACLs, MIC, disk space and later I/O are separate. See
    learn.microsoft.com/windows/win32/api/securitybaseapi/nf-securitybaseapi-accesscheck.
    """
    try:
        if os.name == "nt":
            return _windows(folder)
        return bool(folder.stat().st_mode & 0o222) and os.access(str(folder), os.W_OK | os.X_OK)
    except (AttributeError, OSError, ValueError):
        return False
