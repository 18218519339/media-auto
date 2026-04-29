from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    secret = os.getenv("MEDIA_AUTOMATION_SECRET_KEY", "local-development-secret")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def mask_secret(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}********{value[-2:]}"
