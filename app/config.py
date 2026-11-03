"""Shared profile validation and server-side-only credential storage."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from pydantic import BaseModel, Field, field_validator

SERIAL_RE = re.compile(r"^[A-Za-z0-9_-]{3,128}$")

class ConnectionInput(BaseModel):
    account_id: int = Field(gt=0)
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024)
    program_serial: str

    @field_validator("program_serial")
    @classmethod
    def serial_is_safe(cls, value: str) -> str:
        if not SERIAL_RE.fullmatch(value):
            raise ValueError("Use 3-128 letters, numbers, hyphens, or underscores")
        return value

def data_dir() -> Path:
    return Path(os.environ.get("APP_DB_PATH", "demo/demo.db")).parent

def secret_path() -> Path:
    return Path(os.environ.get("APP_SECRETS_PATH", str(data_dir() / "connection.json")))

def _write_registry(registry: dict) -> None:
    path = secret_path(); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    path.chmod(0o600)

def _read_registry() -> dict:
    path = secret_path()
    if not path.exists(): return {"version": 1, "profiles": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if "profiles" not in raw and "program_serial" in raw:
        serial = raw["program_serial"]
        raw = {"version": 1, "profiles": {serial: {"program_serial": serial, "database": f"{serial}.db", "accounts": [raw]}}}
        _write_registry(raw)
    return raw

def database_path(profile: str) -> Path:
    if profile == "demo": return data_dir() / "demo.db"
    if not SERIAL_RE.fullmatch(profile): raise ValueError("Unknown profile")
    return data_dir() / f"{profile}.db"

def list_profiles() -> list[dict]:
    registry = _read_registry()
    profiles = [{"id": "demo", "label": "Demo sample data", "database": "demo.db", "sample_mode": True, "account_count": 0}]
    for serial, profile in sorted(registry["profiles"].items()):
        profiles.append({"id": serial, "label": serial, "database": profile.get("database", f"{serial}.db"), "sample_mode": bool(profile.get("sample_mode")), "account_count": len(profile.get("accounts", []))})
    return profiles

def is_sample_profile(profile: str) -> bool:
    if profile == "demo":
        return True
    entry = _read_registry()["profiles"].get(profile)
    return bool(entry and entry.get("sample_mode"))

def create_profile(profile: str, source: str) -> dict:
    """Register an empty program profile or a Demo profile for the caller to seed."""
    if profile == "demo" or not SERIAL_RE.fullmatch(profile):
        raise ValueError("Use a unique 3-128 character environment name")
    if source not in {"program", "demo"}:
        raise ValueError("Unknown environment source")
    registry = _read_registry()
    if profile in registry["profiles"]:
        raise ValueError("That environment already exists")
    destination = database_path(profile)
    if destination.exists():
        raise ValueError("A local database already exists for that environment")
    entry = {"program_serial": profile, "database": destination.name, "accounts": []}
    if source == "demo":
        entry["sample_mode"] = True
    registry["profiles"][profile] = entry
    _write_registry(registry)
    return {"id": profile, "label": profile, "database": destination.name, "sample_mode": bool(entry.get("sample_mode")), "account_count": 0}

def connection_summary(profile: str) -> dict:
    if profile == "demo": return {"configured": False, "account_count": 0}
    entry = _read_registry()["profiles"].get(profile)
    accounts = entry.get("accounts", []) if entry else []
    # This is deliberately safe to send to the browser: it identifies saved
    # accounts but never exposes a password or bearer token.
    return {
        "configured": bool(entry),
        "account_count": len(accounts),
        "accounts": [{"account_id": account["account_id"], "username": account["username"], "password_masked": bool(account.get("password"))} for account in accounts],
    }

def stored_connection(profile: str) -> ConnectionInput | None:
    """Return the first saved account for a profile for server-side use only."""
    entry = _read_registry()["profiles"].get(profile)
    if not entry or not entry.get("accounts"):
        return None
    return ConnectionInput.model_validate(entry["accounts"][0])

def stored_connections(profile: str) -> list[ConnectionInput]:
    entry = _read_registry()["profiles"].get(profile)
    return [ConnectionInput.model_validate(account) for account in entry.get("accounts", [])] if entry else []

def save_connection(data: ConnectionInput) -> None:
    registry = _read_registry(); profiles = registry["profiles"]
    profile = profiles.setdefault(data.program_serial, {"program_serial": data.program_serial, "database": f"{data.program_serial}.db", "accounts": []})
    profile.pop("sample_mode", None)
    saved = data.model_dump(); accounts = profile["accounts"]
    profile["accounts"] = [a for a in accounts if not (a["account_id"] == saved["account_id"] and a["username"] == saved["username"])] + [saved]
    _write_registry(registry)

def clear_connection(profile: str) -> None:
    if profile == "demo": return
    registry = _read_registry(); registry["profiles"].pop(profile, None); _write_registry(registry)
