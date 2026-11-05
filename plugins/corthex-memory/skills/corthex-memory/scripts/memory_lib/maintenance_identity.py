"""Read-only, runtime-independent node identities; never maintenance authority.

Identifiers survive a Python upgrade, not arbitrary filesystem rollback. Content,
quiescence, initialization and supported-writer lineage need separate evidence.
"""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import store


class IdentityUnavailable(ValueError):
    def __init__(self):
        super().__init__('maintenance identity unavailable')


def _bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'))+'\n').encode('ascii')


def parse(data):
    """Validate an opaque private record without accessing its alleged node."""
    try:
        value = store.json_document(data)
        kind = value['kind']
        keys = {'version', 'kind', 'entry', 'volume', 'file'}
        if kind == 'posix-fstat':
            keys.add('filesystem')
        if (set(value) != keys or type(value['version']) is not int or value['version'] != 1 or
                kind not in {'windows-file-id', 'posix-fstat'} or value['entry'] not in {'file', 'directory'}):
            raise IdentityUnavailable()
        for name, size in [('volume', 16), ('file', 32)]+([('filesystem', 16)] if 'filesystem' in value else []):
            if not isinstance(value[name], str) or re.fullmatch('[0-9a-f]{'+str(size)+'}', value[name]) is None:
                raise IdentityUnavailable()
        return Identity(_bytes(value))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise IdentityUnavailable() from None


@dataclass(frozen=True)
class Identity:
    encoded: bytes = field(repr=False)

    def document(self):
        return store.json_document(self.encoded)


def _path(path, entry):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or entry not in {'file', 'directory'}:
        raise IdentityUnavailable()
    # Resolve parent aliases, but never resolve the target before inspecting it.
    path = path.parent.resolve(strict=True)/path.name
    _info(path, entry)
    return path


def _info(path, entry):
    info = path.lstat()
    expected = stat.S_ISDIR if entry == 'directory' else stat.S_ISREG
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or not expected(info.st_mode):
        raise IdentityUnavailable()
    return info


def _windows(path, entry):
    import ctypes
    from ctypes import wintypes
    class FileId(ctypes.Structure):
        _fields_ = [('volume', ctypes.c_ulonglong), ('file', ctypes.c_ubyte*16)]
    class Attributes(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('tag', wintypes.DWORD)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    query = kernel.GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    query.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    # No delete sharing while the native node is open; never open a reparse target.
    handle = create(str(path), 0x80, 3, None, 3, 0x02000000 | 0x00200000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise IdentityUnavailable()
    try:
        native, attributes = FileId(), Attributes()
        if not query(handle, 18, ctypes.byref(native), ctypes.sizeof(native)) or not query(
                handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
            raise IdentityUnavailable()
        if attributes.attributes & 0x400 or bool(attributes.attributes & 0x10) != (entry == 'directory'):
            raise IdentityUnavailable()
        return dict(volume=format(native.volume, '016x'), file=bytes(native.file).hex())
    finally:
        if not close(handle):
            raise IdentityUnavailable()


def _posix(path, entry):
    before = _info(path, entry)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    if entry == 'directory':
        flags |= os.O_DIRECTORY
    descriptor = os.open(str(path), flags)
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise IdentityUnavailable()
        expected = stat.S_ISDIR if entry == 'directory' else stat.S_ISREG
        if not expected(opened.st_mode):
            raise IdentityUnavailable()
        filesystem = os.fstatvfs(descriptor).f_fsid
        if (type(filesystem) is not int or not 0 <= opened.st_dev < 2**64 or
                not 0 <= opened.st_ino < 2**128):
            raise IdentityUnavailable()
        after = _info(path, entry)
        if (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino):
            raise IdentityUnavailable()
        return dict(volume=format(opened.st_dev, '016x'), file=format(opened.st_ino, '032x'),
                    filesystem=format(filesystem & (2**64-1), '016x'))
    finally:
        os.close(descriptor)


def capture(path, *, entry='directory'):
    """Inspect a named regular node without reading contents or changing files."""
    try:
        path = _path(path, entry)
        before = _info(path, entry)
        result = _windows(path, entry) if os.name == 'nt' else _posix(path, entry)
        after = _info(path, entry)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise IdentityUnavailable()
        return parse(_bytes(dict(result, version=1, entry=entry,
            kind='windows-file-id' if os.name == 'nt' else 'posix-fstat')))
    except (OSError, ValueError, AttributeError, OverflowError):
        raise IdentityUnavailable() from None


@dataclass(frozen=True)
class Binding:
    path: Path = field(repr=False)
    identity: Identity = field(repr=False)
    pid: int
    _revoked: list = field(default_factory=lambda: [False], repr=False, compare=False)

    def check(self):
        try:
            if self._revoked[0] or os.getpid() != self.pid or capture(
                    self.path, entry=self.identity.document()['entry']) != self.identity:
                raise IdentityUnavailable()
        except Exception:
            self._revoked[0] = True
            raise IdentityUnavailable() from None

    def path_sha256(self):
        self.check()
        return hashlib.sha256(os.path.normcase(str(self.path)).encode('utf-8')).hexdigest()


def bind(path, *, entry='directory'):
    try:
        path = _path(path, entry)
        return Binding(path, capture(path, entry=entry), os.getpid())
    except (OSError, ValueError, AttributeError, RuntimeError):
        raise IdentityUnavailable() from None
