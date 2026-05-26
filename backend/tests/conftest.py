"""Pytest configuration."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="bim_bidding_tests_"))

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TEST_ROOT / 'test.db').as_posix()}")
os.environ.setdefault("UPLOAD_DIR", str(_TEST_ROOT / "uploads"))
os.environ.setdefault("EXPORT_DIR", str(_TEST_ROOT / "exports"))
os.environ.setdefault("FAISS_INDEX_DIR", str(_TEST_ROOT / "faiss"))
os.environ.setdefault("KNOWLEDGE_BASE_TYPE", "none")


def _ensure_fernet_key() -> None:
    if (os.environ.get("SETTINGS_SECRET_KEY") or "").strip():
        return
    from cryptography.fernet import Fernet

    os.environ["SETTINGS_SECRET_KEY"] = Fernet.generate_key().decode()


_ensure_fernet_key()


@pytest.fixture(autouse=True)
def _reset_test_database():
    import app.models  # noqa: F401
    from app.database import engine
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
