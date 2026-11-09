import json
from datetime import date, timedelta

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


def test_orphaned_database_can_be_used_or_explicitly_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app.db import connect
    from app.main import app

    with connect("ExistingDB") as database:
        database.execute("INSERT INTO departments(code,display_name,notes) VALUES(?,?,?)", ("LEGACY", "Legacy cache", "keep"))
    client = TestClient(app)
    conflict = client.post("/api/profiles", json={"profile": "ExistingDB", "source": "program"})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "database_exists"
    adopted = client.post("/api/profiles", json={"profile": "ExistingDB", "source": "program", "existing_database": "use"})
    assert adopted.status_code == 200
    assert any(row["code"] == "LEGACY" for row in client.get("/api/departments?profile=ExistingDB").json())

    with connect("ReplaceDB") as database:
        database.execute("INSERT INTO departments(code,display_name,notes) VALUES(?,?,?)", ("OLD", "Old cache", "replace"))
    replaced = client.post("/api/profiles", json={"profile": "ReplaceDB", "source": "demo", "existing_database": "replace"})
    assert replaced.status_code == 200
    replacement_departments = client.get("/api/departments?profile=ReplaceDB").json()
    assert any(row["code"] == "SharedInfra" for row in replacement_departments)
    assert not any(row["code"] == "OLD" for row in replacement_departments)


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
    assert status["connection"]["account"]["password_masked"] is True


def test_environment_connection_requires_profile_and_does_not_persist_secret(tmp_path, monkeypatch):
    secret_path = tmp_path / "connection.json"
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(secret_path))
    monkeypatch.setenv("FORTIFLEX_CONNECTIONS_JSON", json.dumps({
        "ELAVMR123": {
            "account_id": 12, "username": "environment-reader",
            "password": "environment-only-secret", "program_serial": "ELAVMR123",
        },
    }))
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/profiles").json() == []
    assert client.post("/api/profiles", json={"profile": "ELAVMR123", "source": "program"}).status_code == 200
    environment_status = client.get("/api/status?profile=ELAVMR123").json()
    assert environment_status["connection"]["source"] == "environment"
    assert environment_status["connection"]["account"]["username"] == "environment-reader"
    assert "environment-only-secret" not in secret_path.read_text()
    refused = client.post("/api/setup", json={
        "account_id": 12, "username": "environment-reader", "password": "replacement",
        "program_serial": "ELAVMR123",
    })
    assert refused.status_code == 409

    local = client.post("/api/setup", json={
        "account_id": 34, "username": "local-reader", "password": "local-only-secret",
        "program_serial": "ELAVMR456",
    })
    assert local.status_code == 200
    assert client.get("/api/status?profile=ELAVMR456").json()["connection"]["source"] == "local"


def test_saving_connection_replaces_profile_account(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app.main import app

    client = TestClient(app)
    for account_id, username in ((12, "first"), (34, "second")):
        response = client.post("/api/setup", json={
            "account_id": account_id,
            "username": username,
            "password": "local-only-secret",
            "program_serial": "ELAVMR123",
        })
        assert response.status_code == 200

    connection = client.get("/api/status?profile=ELAVMR123").json()["connection"]
    assert connection["account"] == {"account_id": 34, "username": "second", "password_masked": True}


def test_legacy_multi_account_profile_migrates_to_displayed_account(tmp_path, monkeypatch):
    secret_path = tmp_path / "connection.json"
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(secret_path))
    secret_path.write_text(json.dumps({"version": 1, "profiles": {
        "ELAVMR123": {"program_serial": "ELAVMR123", "accounts": [
            {"account_id": 12, "username": "shown", "password": "first"},
            {"account_id": 34, "username": "hidden", "password": "second"},
        ]}
    }}))
    from app.config import connection_summary

    assert connection_summary("ELAVMR123")["account"]["username"] == "shown"
    migrated = json.loads(secret_path.read_text())
    assert migrated["profiles"]["ELAVMR123"]["connection"]["account_id"] == 12
    assert "accounts" not in migrated["profiles"]["ELAVMR123"]


def test_department_create_edit_and_safe_delete(tmp_path, monkeypatch):
    client = client_with_demo(tmp_path, monkeypatch)
    created = client.post("/api/departments?profile=DemoTest", json={
        "code": "LAB", "display_name": "Lab systems", "notes": "temporary",
    })
    assert created.status_code == 200
    edited = client.put("/api/departments/LAB?profile=DemoTest", json={
        "code": "LAB", "display_name": "Laboratory", "notes": "updated",
    })
    assert edited.status_code == 200
    departments = client.get("/api/departments?profile=DemoTest").json()
    assert next(row for row in departments if row["code"] == "LAB")["display_name"] == "Laboratory"
    assert client.delete("/api/departments/LAB?profile=DemoTest").status_code == 200

    assigned_code = client.get("/api/departments?profile=DemoTest").json()[0]["code"]
    refused = client.delete(f"/api/departments/{assigned_code}?profile=DemoTest")
    assert refused.status_code == 409


def test_api_samples_are_memory_only_and_recursively_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app.debug import record
    from app.main import app

    record("DebugTest", "Entitlement inventory", "/entitlements/list", {
        "accountId": 12, "password": "never-return-this",
    }, {
        "access_token": "never-return-this-either",
        "nested": {"apiKey": "also-secret", "status": 0},
        "entitlements": [{"serialNumber": f"FGVM{i}"} for i in range(6)],
    })
    response = TestClient(app).get("/api/debug/log?profile=DebugTest")

    assert response.status_code == 200
    encoded = response.text
    assert "never-return-this" not in encoded
    assert "also-secret" not in encoded
    sample = response.json()["samples"][0]
    assert sample["request"]["authorization"] == "Bearer <redacted>"
    assert sample["response"]["metadata"]["access_token"] == "<redacted>"
    assert sample["response"]["record_count"] == 6
    assert len(sample["response"]["records"]) == 5
    assert sample["response"]["truncated"] is True


def test_api_sample_is_fabricated_and_limited_to_five_records(tmp_path, monkeypatch):
    client = client_with_demo(tmp_path, monkeypatch)
    response = client.get("/api/debug/sample")

    assert response.status_code == 200
    samples = response.json()["samples"]
    assert len(samples) == 3
    assert all(sample["fabricated"] is True for sample in samples)
    assert all(sample["request"]["body"]["accountId"] == 12345 for sample in samples)
    assert all(len(sample["response"]["sample_records"]) == 5 for sample in samples)
    assert samples[1]["response"]["sample_records"][0]["name"] == "SampleFGT1"
    assert {record["productType"] for record in samples[1]["response"]["sample_records"]} >= {
        "FortiGate Virtual Machine", "FortiWeb Virtual Machine", "FortiManager Virtual Machine", "FortiAnalyzer Virtual Machine",
    }
    assert all("ELT" not in record["serialNumber"] for record in samples[0]["response"]["sample_records"])


def test_demo_seeded_serials_are_obviously_fabricated(tmp_path, monkeypatch):
    client = client_with_demo(tmp_path, monkeypatch)
    devices = client.get("/api/devices?profile=DemoTest&status=ACTIVE,PENDING").json()
    assert devices
    assert all(device["serial"].startswith("SAMPLE-") for device in devices)


def test_delete_usage_date_range_clears_local_cache_and_coverage(tmp_path, monkeypatch):
    client = client_with_demo(tmp_path, monkeypatch)
    from app.db import connect

    start = date.today() - timedelta(days=160)
    end = start + timedelta(days=1)
    with connect("DemoTest") as database:
        serial = database.execute("SELECT serial FROM devices LIMIT 1").fetchone()[0]
        for day in (start, end):
            database.execute(
                "INSERT INTO usage_records(serial,usage_date,points,source,refreshed_at) VALUES(?,?,?,?,?)",
                (serial, day.isoformat(), 5, "test", "now"),
            )
            database.execute(
                "INSERT INTO usage_day_coverage(account_id,usage_date,status,detail,refreshed_at) VALUES(?,?,?,?,?)",
                (123, day.isoformat(), "complete", "", "now"),
            )

    response = client.post("/api/usage/dates/delete?profile=DemoTest", json={
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    })

    assert response.status_code == 200
    assert response.json()["usage_records_deleted"] == 2
    assert response.json()["coverage_records_deleted"] == 2
    with connect("DemoTest") as database:
        assert database.execute("SELECT COUNT(*) FROM usage_records WHERE usage_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat())).fetchone()[0] == 0
        assert database.execute("SELECT COUNT(*) FROM usage_day_coverage WHERE usage_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat())).fetchone()[0] == 0


def test_pricing_uses_only_active_cached_configurations(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app import main
    from app.db import connect

    client = TestClient(main.app)
    client.post("/api/setup", json={"account_id": 12, "username": "reader", "password": "secret", "program_serial": "PriceTest"})
    features = json.dumps({"parameters": [{"id": 1, "name": "Number of CPUs", "value": "2"}, {"id": 2, "name": "Service Package", "value": "UTP"}]})
    with connect("PriceTest") as database:
        database.execute("INSERT INTO configurations(config_id,product,config_name,features,status,notes,refreshed_at) VALUES(?,?,?,?,?,?,?)", (1, "FortiGate-VM", "active", features, "ACTIVE", "", "now"))
        database.execute("INSERT INTO configurations(config_id,product,config_name,features,status,notes,refreshed_at) VALUES(?,?,?,?,?,?,?)", (2, "FortiGate-VM", "disabled", features, "DISABLED", "", "now"))
    monkeypatch.setattr(main, "token", lambda account: "test-token")
    monkeypatch.setattr(main, "pricing_metadata", lambda *args: [{"productTypeId": 1, "name": "FortiGate Virtual Machine - Service Bundle", "parameters": [{"name": "Number of CPUs"}, {"name": "Service Package"}]}])
    calls = []
    def calculate(_account, _token, product_type_id, parameters, capture):
        calls.append((product_type_id, parameters))
        capture("/tools/calc", {"productTypeId": product_type_id, "parameters": parameters}, {"status": 0, "configs": {"current": 3.5, "latest": 4.0, "latestEffectiveDate": "2027-01-01"}})
        return {"current": 3.5, "latest": 4.0, "latestEffectiveDate": "2027-01-01"}
    monkeypatch.setattr(main, "calculate_points", calculate)

    response = client.post("/api/configurations/prices?profile=PriceTest")

    assert response.status_code == 200
    assert response.json()["active"] == 1
    assert response.json()["priced"] == 1
    assert calls == [(1, [{"id": 1, "value": "2"}, {"id": 2, "value": "UTP"}])]
    configurations = client.get("/api/configurations?profile=PriceTest").json()
    assert configurations[0]["points_per_day"] == 3.5
    assert configurations[1]["points_per_day"] is None
    log = client.get("/api/debug/log?profile=PriceTest").json()["samples"]
    assert any(sample["operation"] == "Configuration pricing" for sample in log)


def test_pull_week_uses_only_last_seven_complete_days(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "runtime.db"))
    monkeypatch.setenv("APP_SECRETS_PATH", str(tmp_path / "connection.json"))
    from app import main
    from app.db import connect

    client = TestClient(main.app)
    client.post("/api/setup", json={
        "account_id": 12,
        "username": "reader",
        "password": "local-only-secret",
        "program_serial": "ELAVMR123",
    })
    yesterday = date.today() - timedelta(days=1)
    with connect("ELAVMR123") as database:
        database.execute(
            "INSERT INTO usage_day_coverage(account_id,usage_date,status,detail,refreshed_at) VALUES(?,?,?,?,?)",
            (12, yesterday.isoformat(), "complete", "", "now"),
        )

    launched = {}
    class FakeThread:
        def __init__(self, *, target, args, daemon):
            launched.update(target=target, args=args, daemon=daemon)
        def start(self):
            return None
    monkeypatch.setattr(main.threading, "Thread", FakeThread)
    response = client.post("/api/pull/missing?profile=ELAVMR123")
    if main.PULL_LOCK.locked():
        main.PULL_LOCK.release()

    assert response.status_code == 200
    assert launched["args"][1] == [
        (yesterday - timedelta(days=offset)).isoformat() for offset in range(6, 0, -1)
    ]
