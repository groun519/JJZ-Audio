from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Protocol


class CredentialStore(Protocol):
    def read(self, target: str) -> str | None: ...

    def write(self, target: str, secret: str) -> None: ...

    def delete(self, target: str) -> None: ...


class WindowsCredentialError(RuntimeError):
    """Raised when Windows Credential Manager cannot complete an operation."""


class _CredentialAttribute(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CredentialAttribute)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialStore:
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168
    _MAX_BLOB_BYTES = 2560

    def __init__(self, username: str = "JJZero Audio") -> None:
        if sys.platform != "win32":
            raise WindowsCredentialError("Windows Credential Manager is only available on Windows.")
        self._username = username
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._configure_functions()

    def read(self, target: str) -> str | None:
        credential_pointer = ctypes.POINTER(_Credential)()
        if not self._advapi32.CredReadW(
            target,
            self._CRED_TYPE_GENERIC,
            0,
            ctypes.byref(credential_pointer),
        ):
            error = ctypes.get_last_error()
            if error == self._ERROR_NOT_FOUND:
                return None
            raise WindowsCredentialError(f"Credential read failed with Windows error {error}.")
        try:
            credential = credential_pointer.contents
            if not credential.CredentialBlob or credential.CredentialBlobSize <= 0:
                return ""
            value = ctypes.string_at(
                credential.CredentialBlob,
                credential.CredentialBlobSize,
            )
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WindowsCredentialError("Stored credential is not valid UTF-8.") from exc
        finally:
            self._advapi32.CredFree(credential_pointer)

    def write(self, target: str, secret: str) -> None:
        value = secret.encode("utf-8")
        if len(value) > self._MAX_BLOB_BYTES:
            raise WindowsCredentialError("Credential exceeds the Windows storage limit.")
        blob = (ctypes.c_ubyte * max(1, len(value)))()
        if value:
            ctypes.memmove(blob, value, len(value))
        credential = _Credential(
            Type=self._CRED_TYPE_GENERIC,
            TargetName=target,
            CredentialBlobSize=len(value),
            CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=self._CRED_PERSIST_LOCAL_MACHINE,
            UserName=self._username,
        )
        if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
            error = ctypes.get_last_error()
            raise WindowsCredentialError(f"Credential write failed with Windows error {error}.")

    def delete(self, target: str) -> None:
        if self._advapi32.CredDeleteW(target, self._CRED_TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self._ERROR_NOT_FOUND:
            raise WindowsCredentialError(f"Credential delete failed with Windows error {error}.")

    def _configure_functions(self) -> None:
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredWriteW.argtypes = [
            ctypes.POINTER(_Credential),
            wintypes.DWORD,
        ]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [wintypes.LPVOID]
        self._advapi32.CredFree.restype = None
