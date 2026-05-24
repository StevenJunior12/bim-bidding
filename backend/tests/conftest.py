"""Pytest configuration."""
from __future__ import annotations

import os


def _ensure_fernet_key() -> None:
    if (os.environ.get("SETTINGS_SECRET_KEY") or "").strip():
        return
    from cryptography.fernet import Fernet

    os.environ["SETTINGS_SECRET_KEY"] = Fernet.generate_key().decode()


_ensure_fernet_key()
