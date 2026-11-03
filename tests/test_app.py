from fastapi.testclient import TestClient


def client_with_demo(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app.config import create_profile
    from app.seed import seed
    from app.main import app

    create_profile("DemoTest", "demo")
    seed("DemoTest")
    return TestClient(app)


def test_demo_profile_dashboard_and_static_assets(tmp_path, monkeypatch):
    client = client_with_demo(tmp_path, monkeypatch)

    profiles = client.get("/api/profiles").json()
    assert profiles == [{
        "id": "DemoTest",
        "label": "DemoTest",
        "database": "DemoTest.db",
        "sample_mode": True,
        "account_count": 0,
    }]
    assert client.get("/api/status?profile=DemoTest").json()["sample_mode"] is True
    dashboard = client.get("/api/dashboard?profile=DemoTest&view=30").json()
    assert dashboard["points"] > 0
    assert len(dashboard["series"]) == 30
    assert client.get("/static/fortinet-white.svg").status_code == 200
    assert client.get("/static/theme-options.js").status_code == 200


def test_setup_never_returns_password(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app.main import app
    response = TestClient(app).post("/api/setup", json={
        "account_id": 12,
        "username": "reader",
        "password": "not-in-response",
        "program_serial": "ELAVMR123",
    })

    assert "not-in-response" not in response.text
    assert response.json()["connection"]["username"] == "reader"
    status = TestClient(app).get("/api/status?profile=ELAVMR123").json()
    assert status["connection"]["accounts"][0]["password_masked"] is True
