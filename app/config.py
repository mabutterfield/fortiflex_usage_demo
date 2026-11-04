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
        raw = {"version": 2, "profiles": {serial: {"program_serial": serial, "database": f"{serial}.db", "connection": raw}}}
        _write_registry(raw)
    # Version 1 allowed more than one account inside a profile. The UI only
    # ever showed the first one, so retain that same connection on migration.
    # New profiles have exactly one connection; use a separate profile for a
    # separate FortiFlex account/program.
    changed = False
    for profile in raw["profiles"].values():
        if "accounts" in profile:
            accounts = profile.pop("accounts")
            if accounts:
                profile["connection"] = accounts[0]
            changed = True
    if changed:
        raw["version"] = 2
        _write_registry(raw)
    return raw

def database_path(profile: str) -> Path:
    if not SERIAL_RE.fullmatch(profile): raise ValueError("Unknown profile")
    return data_dir() / f"{profile}.db"

def list_profiles() -> list[dict]:
    registry = _read_registry()
    profiles = []
    for serial, profile in sorted(registry["profiles"].items()):
        profiles.append({"id": serial, "label": serial, "database": profile.get("database", f"{serial}.db"), "sample_mode": bool(profile.get("sample_mode")), "account_count": int(bool(profile.get("connection")))})
    return profiles

def is_sample_profile(profile: str) -> bool:
    entry = _read_registry()["profiles"].get(profile)
    return bool(entry and entry.get("sample_mode"))

def create_profile(profile: str, source: str) -> dict:
    """Register an empty program profile or a Demo profile for the caller to seed."""
    if not SERIAL_RE.fullmatch(profile):
        raise ValueError("Use a unique 3-128 character environment name")
    if source not in {"program", "demo"}:
        raise ValueError("Unknown environment source")
    registry = _read_registry()
    if profile in registry["profiles"]:
        raise ValueError("That environment already exists")
    destination = database_path(profile)
    if destination.exists():
        raise ValueError("A local database already exists for that environment")
    entry = {"program_serial": profile, "database": destination.name}
    if source == "demo":
        entry["sample_mode"] = True
    registry["profiles"][profile] = entry
    _write_registry(registry)
    return {"id": profile, "label": profile, "database": destination.name, "sample_mode": bool(entry.get("sample_mode")), "account_count": 0}

def connection_summary(profile: str) -> dict:
    entry = _read_registry()["profiles"].get(profile)
    account = entry.get("connection") if entry else None
    # This is deliberately safe to send to the browser: it identifies saved
    # accounts but never exposes a password or bearer token.
    return {
        "configured": bool(account),
        "account": {"account_id": account["account_id"], "username": account["username"], "password_masked": bool(account.get("password"))} if account else None,
    }

def stored_connection(profile: str) -> ConnectionInput | None:
    """Return the one saved account for a profile for server-side use only."""
    entry = _read_registry()["profiles"].get(profile)
    if not entry or not entry.get("connection"):
        return None
    return ConnectionInput.model_validate(entry["connection"])

def save_connection(data: ConnectionInput) -> None:
    registry = _read_registry(); profiles = registry["profiles"]
    profile = profiles.setdefault(data.program_serial, {"program_serial": data.program_serial, "database": f"{data.program_serial}.db"})
    profile.pop("sample_mode", None)
    profile["connection"] = data.model_dump()
    _write_registry(registry)

def clear_connection(profile: str) -> None:
    registry = _read_registry()
    if profile in registry["profiles"]:
        registry["profiles"][profile].pop("connection", None)
        _write_registry(registry)

def delete_profile(profile: str) -> None:
    """Remove exactly one locally managed profile and its SQLite files."""
    registry = _read_registry()
    if profile not in registry["profiles"]:
        raise ValueError("Profile not found")
    database = database_path(profile)
    for path in (database, Path(str(database) + "-wal"), Path(str(database) + "-shm")):
        if path.exists():
            path.unlink()
    registry["profiles"].pop(profile)
    _write_registry(registry)
