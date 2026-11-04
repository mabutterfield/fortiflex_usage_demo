"""In-memory, redacted API samples for the local debug tray.

Samples are deliberately not written to SQLite, logs, or connection.json.
Only the most recent successful example for each supported read operation is
kept per profile until the application restarts.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from threading import Lock
from typing import Any

SENSITIVE = ("authorization", "password", "token", "secret", "credential", "apikey", "api_key")
_samples: dict[str, dict[str, dict[str, Any]]] = {}
_lock = Lock()


def _redact(value: Any, key: str = "") -> Any:
    if any(word in key.lower() for word in SENSITIVE):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.lower().startswith("bearer "):
        return "Bearer <redacted>"
    return value


def _records(response: dict) -> tuple[list, dict]:
    """Extract the first list-like API result while preserving useful metadata."""
    summary = {key: value for key, value in response.items() if key not in {"entitlements", "configurations", "configs", "data"}}
    for key in ("entitlements", "configurations", "configs", "data"):
        value = response.get(key)
        if isinstance(value, list):
            return value, summary
        if isinstance(value, dict):
            flattened = [dict(item, _group=group) for group, items in value.items() for item in (items if isinstance(items, list) else []) if isinstance(item, dict)]
            if flattened:
                return flattened, summary
    return [], summary


def record(profile: str, operation: str, endpoint: str, request: dict, response: dict) -> None:
    """Keep one safe sample for a supported FortiFlex read operation."""
    records, metadata = _records(response)
    sample = {
        "operation": operation,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": endpoint,
        "request": {"body": _redact(request), "authorization": "Bearer <redacted>"},
        "response": {
            "metadata": _redact(metadata),
            "record_count": len(records),
            "sample_records": _redact(records[:5]),
        },
    }
    with _lock:
        _samples.setdefault(profile, {})[operation] = sample


def samples(profile: str) -> list[dict]:
    with _lock:
        return list(_samples.get(profile, {}).values())


def demo_samples() -> list[dict]:
    """Return clearly fabricated examples that can be viewed in any profile."""
    today = date.today().isoformat()
    request = {"accountId": 12345, "programSerialNumber": "SAMPLE-PROGRAM-12345"}
    inventory = [
        {"serialNumber": serial, "description": f"Sample description — {product}", "configId": config_id, "accountId": 12345, "startDate": today, "endDate": "2028-12-31", "status": "ACTIVE"}
        for serial, config_id, product in (
            ("SAMPLE-FGT-VM-0001", 801, "FortiGate VM"),
            ("SAMPLE-FWB-VM-0001", 802, "FortiWeb VM"),
            ("SAMPLE-FMG-VM-0001", 803, "FortiManager VM"),
            ("SAMPLE-FAZ-VM-0001", 804, "FortiAnalyzer VM"),
            ("SAMPLE-FGT-HW-0001", 805, "FortiGate hardware"),
            ("SAMPLE-FWB-VM-0002", 806, "FortiWeb VM"),
        )
    ]
    configurations = [
        {"configId": config_id, "name": name, "productType": product, "status": "ACTIVE"}
        for config_id, name, product in (
            (801, "SampleFGT1", "FortiGate Virtual Machine"),
            (802, "SampleFWB1", "FortiWeb Virtual Machine"),
            (803, "SampleFMG1", "FortiManager Virtual Machine"),
            (804, "SampleFAZ1", "FortiAnalyzer Virtual Machine"),
            (805, "SampleFGT2", "FortiGate Hardware"),
            (806, "SampleFWB2", "FortiWeb Virtual Machine"),
        )
    ]
    points = [
        {"serialNumber": item["serialNumber"], "accountId": 12345, "points": value}
        for item, value in zip(inventory, (2.0, 4.0, 6.0, 8.0, 12.0, 16.0), strict=True)
    ]
    return [
        _sample("Entitlement inventory", "/entitlements/list", request, {"status": 0, "message": "Sample response", "entitlements": inventory}),
        _sample("Configuration catalogue", "/configs/list", request, {"status": 0, "message": "Sample response", "configurations": configurations}),
        _sample("Daily point usage", "/entitlements/points", {**request, "startDate": today, "endDate": today}, {"status": 0, "message": "Sample response", "entitlements": points}),
    ]


def _sample(operation: str, endpoint: str, request: dict, response: dict) -> dict:
    records, metadata = _records(response)
    return {
        "operation": operation,
        "captured_at": f"{date.today().isoformat()}T00:00:00Z",
        "endpoint": endpoint,
        "request": {"body": _redact(request), "authorization": "Bearer <redacted>"},
        "response": {"metadata": _redact(metadata), "record_count": len(records), "sample_records": _redact(records[:5])},
        "sample_data": True,
    }
