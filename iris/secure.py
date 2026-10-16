"""Encrypt small secrets for the current user, using the operating system itself (no extra package, no password to remember).

* Windows: DPAPI. The data can only be opened by the same Windows account on the same PC.
  Copying the file to another PC or user (or a backup stolen from disk) gives unreadable bytes.
* Elsewhere: not available here, so callers keep the file private with permissions instead.
"""
import sys

ENTROPY = b"iris-vault-v1"           # extra salt so another program's DPAPI blobs are not accepted as ours


def available() -> bool:
    return sys.platform.startswith("win")


if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes

    class _BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_BLOB),
                                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_BLOB), ctypes.c_void_p, ctypes.POINTER(_BLOB),
                                            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_BLOB)]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _UI_FORBIDDEN = 0x1

    def _blob(data: bytes):
        buf = ctypes.create_string_buffer(data, len(data))
        return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf   # keep buf alive

    def _take(out: "_BLOB") -> bytes:
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def protect(data: bytes) -> bytes:
        src, keep1 = _blob(data)
        ent, keep2 = _blob(ENTROPY)
        out = _BLOB()
        if not _crypt32.CryptProtectData(ctypes.byref(src), "Iris", ctypes.byref(ent), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(f"Windows could not encrypt the data (error {ctypes.get_last_error()}).")
        return _take(out)

    def unprotect(data: bytes) -> bytes:
        src, keep1 = _blob(data)
        ent, keep2 = _blob(ENTROPY)
        out = _BLOB()
        if not _crypt32.CryptUnprotectData(ctypes.byref(src), None, ctypes.byref(ent), None, None, _UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(f"Windows could not decrypt the data (error {ctypes.get_last_error()}).")
        return _take(out)

else:
    def protect(data: bytes) -> bytes:        # pragma: no cover - never called when available() is False
        raise OSError("No system encryption on this platform.")

    def unprotect(data: bytes) -> bytes:      # pragma: no cover
        raise OSError("No system encryption on this platform.")
