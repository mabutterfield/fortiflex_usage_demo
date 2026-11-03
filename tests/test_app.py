import os
from pathlib import Path
from fastapi.testclient import TestClient

def test_sample_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path/"demo.db")); monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path/"secret.json"))
    from app.seed import seed; seed()
    from app.main import app
    client=TestClient(app)
    assert client.get("/api/status").json()["sample_mode"] is True
    data=client.get("/api/summary").json()
    assert len(data) == 4 and all("points" in item for item in data)

def test_setup_never_returns_password(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path/"secret.json"))
    from app.main import app
    response=TestClient(app).post("/api/setup", json={"account_id":12,"username":"reader","password":"not-in-response","program_serial":"ELAVMR123"})
    assert "not-in-response" not in response.text
    assert response.json()["connection"]["username"] == "reader"
