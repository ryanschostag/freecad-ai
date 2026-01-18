"""Pytest path bootstrap.

These tests import the FastAPI app via `from app.main import app`.

In Docker, the API service typically sets PYTHONPATH so `services/api` is already on
`sys.path`. When running pytest locally from the repo root, that may not be true,
so `import app` can fail.

We make the import robust by ensuring both the repo root and `services/api` are on
`sys.path`.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_on_syspath(p: Path) -> None:
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


# This file lives at: <repo>/services/api/app/tests/conftest.py
REPO_ROOT = Path(__file__).resolve().parents[4]
API_ROOT = REPO_ROOT / "services" / "api"

_ensure_on_syspath(REPO_ROOT)
_ensure_on_syspath(API_ROOT)
