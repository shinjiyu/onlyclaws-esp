"""Shared fixtures: the FastAPI app on a throwaway data dir, and a login helper."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session")
def oc_app():
    data = Path(tempfile.mkdtemp(prefix="oc-test-"))
    os.environ["EPD_DATA_DIR"] = str(data)
    os.environ["EPD_SESSION_SECRET"] = "test-secret"
    os.environ["EPD_ALLOWLIST"] = "*"
    os.environ["EPD_SCRIPT_SIGNING_KEY"] = str(data / "no-key.pem")
    import app as app_module

    return app_module


@pytest.fixture
def client(oc_app):
    from fastapi.testclient import TestClient

    with TestClient(oc_app.app, base_url="https://testserver") as c:
        yield c


@pytest.fixture
def login(oc_app):
    def _login(client, email: str) -> None:
        client.cookies.clear()
        token = oc_app.serializer.dumps({"email": email, "user": {"email": email}})
        client.cookies.set(oc_app.SESSION_COOKIE, token)

    return _login
