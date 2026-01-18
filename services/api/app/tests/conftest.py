"""Pytest path bootstrap.

These tests import the FastAPI app via `from app.main import app`.

In Docker, the API service typically sets PYTHONPATH so `services/api` is already on
`sys.path`. When running pytest locally from the repo root, that may not be true,
so `import app` can fail.

We make the import robust by ensuring both the repo root and `services/api` are on
`sys.path`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_on_syspath(p: Path) -> None:
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)


def _find_repo_root() -> Path:
    env = os.getenv("REPO_ROOT")
    if env:
        return Path(env).resolve()

    docker_root = Path("/app")
    if docker_root.exists():
        return docker_root.resolve()

    p = Path(__file__).resolve()
    for _ in range(12):
        if (p / "docker-compose.yml").exists() or (p / "pyproject.toml").exists() or (p / ".git").exists():
            return p
        if p.parent == p:
            break
        p = p.parent
    return Path(__file__).resolve().parent


REPO_ROOT = _find_repo_root()
API_ROOT = REPO_ROOT / "services" / "api"

_ensure_on_syspath(REPO_ROOT)
_ensure_on_syspath(API_ROOT)
