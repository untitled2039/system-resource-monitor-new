"""Encrypt secrets (API keys) with Windows DPAPI before writing them to config.json.

DPAPI ties the encrypted value to the current Windows user account: another user, or the
same file copied to another PC, cannot decrypt it. On other platforms the value is kept
as-is (the monitor app itself only runs on Windows).
"""
import base64
import sys

_ENTROPY = b"SystemResourceMonitor/api-key"


def available():
    return sys.platform == "win32"


_DATA_BLOB = None


def _blob_type():
    """DATA_BLOB structure, created once so every call uses the same ctypes type."""
    global _DATA_BLOB
    if _DATA_BLOB is None:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        _DATA_BLOB = DATA_BLOB
    return _DATA_BLOB


def _to_blob(data):
    import ctypes
    blob_type = _blob_type()
    buffer = ctypes.create_string_buffer(data, len(data))
    return blob_type(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _call(function_name, data):
    import ctypes
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")
    blob_type = _blob_type()
    function = getattr(crypt32, function_name)
    function.argtypes = [ctypes.POINTER(blob_type), ctypes.c_void_p, ctypes.POINTER(blob_type),
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(blob_type)]
    function.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    data_in, _keep_data = _to_blob(data)
    entropy, _keep_entropy = _to_blob(_ENTROPY)
    data_out = blob_type()
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    if not function(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
                    CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out)):
        raise OSError(f"{function_name} failed (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(data_out.pbData)


def protect(text):
    """Return an encrypted, base64-encoded form of text."""
    encrypted = _call("CryptProtectData", text.encode("utf-8"))
    return base64.b64encode(encrypted).decode("ascii")


def unprotect(token):
    """Decrypt a value produced by protect(). Raises OSError if it cannot be decrypted."""
    decrypted = _call("CryptUnprotectData", base64.b64decode(token))
    return decrypted.decode("utf-8")
