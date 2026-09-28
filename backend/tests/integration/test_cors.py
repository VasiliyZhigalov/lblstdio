from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}",
        storage_root=tmp_path / "storage",
    )
    with TestClient(app) as test_client:
        yield test_client


def test_cors_allows_localhost_and_rejects_other_origins(client: TestClient) -> None:
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert allowed.status_code == 200
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    blocked = client.get("/health", headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 200
    assert blocked.headers.get("access-control-allow-origin") is None
