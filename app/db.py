from __future__ import annotations
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from .config import database_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
 serial TEXT PRIMARY KEY, friendly_name TEXT NOT NULL, department_code TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '', product TEXT NOT NULL,
 portal_name TEXT, entitlement_status TEXT, config_id INTEGER,
 entitlement_start_date TEXT, entitlement_end_date TEXT
);
CREATE TABLE IF NOT EXISTS departments (
 code TEXT PRIMARY KEY, display_name TEXT NOT NULL, notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS usage_records (
 serial TEXT NOT NULL REFERENCES devices(serial), usage_date TEXT NOT NULL,
 points REAL, source TEXT NOT NULL, refreshed_at TEXT NOT NULL,
 PRIMARY KEY(serial, usage_date)
);
CREATE TABLE IF NOT EXISTS refresh_state (
 id INTEGER PRIMARY KEY CHECK(id=1), status TEXT NOT NULL, message TEXT NOT NULL, refreshed_at TEXT
);
CREATE TABLE IF NOT EXISTS usage_day_coverage (
 account_id INTEGER NOT NULL, usage_date TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('complete','failed')),
 detail TEXT NOT NULL DEFAULT '', refreshed_at TEXT NOT NULL,
 PRIMARY KEY(account_id, usage_date)
);
CREATE TABLE IF NOT EXISTS configurations (
 config_id INTEGER PRIMARY KEY, product TEXT NOT NULL DEFAULT '',
 config_name TEXT NOT NULL DEFAULT '', features TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT '',
 notes TEXT NOT NULL DEFAULT '', refreshed_at TEXT NOT NULL DEFAULT '',
 points_per_day REAL, latest_points_per_day REAL, pricing_effective_date TEXT,
 priced_at TEXT, pricing_status TEXT NOT NULL DEFAULT ''
);
INSERT OR IGNORE INTO refresh_state VALUES(1, 'ready', 'Sample data loaded', NULL);
"""

def path(profile: str = "demo") -> Path:
    return database_path(profile)

@contextmanager
def connect(profile: str = "demo"):
    p = path(profile); p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)")}
    for column, definition in (
        ("portal_name", "TEXT"), ("entitlement_status", "TEXT"), ("config_id", "INTEGER"),
        ("entitlement_start_date", "TEXT"), ("entitlement_end_date", "TEXT"),
    ):
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE devices ADD COLUMN {column} {definition}")
    configuration_columns = {row["name"] for row in conn.execute("PRAGMA table_info(configurations)")}
    for column, definition in (
        ("config_name", "TEXT NOT NULL DEFAULT ''"),
        ("points_per_day", "REAL"), ("latest_points_per_day", "REAL"),
        ("pricing_effective_date", "TEXT"), ("priced_at", "TEXT"),
        ("pricing_status", "TEXT NOT NULL DEFAULT ''"),
    ):
        if column not in configuration_columns:
            conn.execute(f"ALTER TABLE configurations ADD COLUMN {column} {definition}")
    # Existing caches already contain the raw structured feature document.
    # Derive the portal configuration name locally without another API call.
    for row in conn.execute("SELECT config_id,features FROM configurations WHERE config_name=''"):
        try:
            name = json.loads(row["features"]).get("name", "")
            if name:
                conn.execute("UPDATE configurations SET config_name=? WHERE config_id=?", (str(name), row["config_id"]))
        except (ValueError, TypeError):
            pass
    conn.execute("UPDATE devices SET portal_name=friendly_name WHERE portal_name IS NULL")
    conn.execute("""UPDATE devices SET
        entitlement_status=COALESCE(entitlement_status, trim(substr(notes, 18, instr(notes, ';') - 18))),
        config_id=COALESCE(config_id, CAST(substr(notes, instr(notes, 'configuration:') + length('configuration:') + 1) AS INTEGER)),
        notes=CASE WHEN notes LIKE 'FortiFlex status: %; configuration: %' THEN '' ELSE notes END
        WHERE notes LIKE 'FortiFlex status: %; configuration: %'""")
    conn.execute("INSERT OR IGNORE INTO departments(code,display_name) SELECT DISTINCT department_code, department_code FROM devices")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
