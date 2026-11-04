"""Create the deliberately fabricated Demo profile database."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from .db import connect


DEPARTMENTS = (
    ("SharedInfra", "Shared infrastructure", "FortiAnalyzer and FortiManager services"),
    ("Cloud", "Cloud", "Cloud-hosted FortiGate VMs"),
    ("R&D", "Research and development", "Lab and development perimeter hardware"),
    ("Core", "Core", "Core network perimeter hardware"),
)

# These records resemble the useful portions of a FortiFlex configuration
# response but use invented IDs and labels. They must never be mistaken for a
# product catalogue or a copy of a customer's live configuration database.
CONFIGURATIONS = (
    (1101, "FortiGate-VM", "FG-vm01-UTP", "ACTIVE", [("Number of CPUs", "1"), ("Service Package", "UTP")]),
    (1102, "FortiGate-VM", "fg-vm02-ENT", "ACTIVE", [("Number of CPUs", "2"), ("Service Package", "ENT")]),
    (1104, "FortiGate-VM", "fg-vm04-FC", "ACTIVE", [("Number of CPUs", "4"), ("Service Package", "FC")]),
    (2101, "FortiAnalyzer-VM", "FAZ-10GB", "ACTIVE", [("Daily Storage (GB)", "10"), ("Support Services", "FAZFC247"), ("Addons", "FAZISSS"), ("Addons", "FAZFGSA"), ("Addons", "FAZAISN")]),
    (2201, "FortiManager-VM", "FMG-10device", "ACTIVE", [("Device Count", "10"), ("Support Services", "FMGFC247")]),
    (3101, "FortiGate-Hardware", "FG-2600F-UTP", "ACTIVE", [("Device Model", "FGT2600F"), ("Service Package", "FGHWUTP")]),
    (3120, "FortiGate-Hardware", "fg-120G-ENT", "ACTIVE", [("Device Model", "FGT120G"), ("Service Package", "FGHWENT")]),
)


def _device(serial: str, name: str, department: str, product: str, config_id: int, status: str = "ACTIVE", note: str = "") -> tuple:
    return (serial, name, department, note, product, name, status, config_id, "2026-01-01", "2027-01-01")


def _devices() -> list[tuple]:
    rows: list[tuple] = []
    # Six fabricated entitlements per FortiGate configuration size/profile.
    for config_id, label, serial_prefix in (
        (1101, "cloud-fg01", "SAMPLE-FGVM-01-"),
        (1102, "cloud-fg02", "SAMPLE-FGVM-02-"),
        (1104, "cloud-fg04", "SAMPLE-FGVM-04-"),
    ):
        for number in range(1, 7):
            rows.append(_device(f"{serial_prefix}{number:03d}", f"{label}-{number:02d}", "Cloud", "FortiGate-VM", config_id))
    for config_id, label, serial_prefix, department, count in (
        (3101, "core-fg2600f", "SAMPLE-FGT-2600F-", "Core", 4),
        (3120, "rnd-fg120g", "SAMPLE-FGT-120G-", "R&D", 6),
    ):
        for number in range(1, count + 1):
            status = "STOPPED" if config_id == 3120 and number == count else "ACTIVE"
            rows.append(_device(f"{serial_prefix}{number:04d}", f"{label}-{number:02d}", department, "FortiGate-Hardware", config_id, status))
    for number in range(1, 3):
        rows.append(_device(f"SAMPLE-FAZ-VM-{number:02d}", f"shared-faz-{number:02d}", "SharedInfra", "FortiAnalyzer-VM", 2101))
        rows.append(_device(f"SAMPLE-FMG-VM-{number:02d}", f"shared-fmg-{number:02d}", "SharedInfra", "FortiManager-VM", 2201))
    return rows


DAILY_CONFIG_POINTS = {
    1101: 1.0,   # FG-vm01-UTP
    1102: 2.0,   # fg-vm02-ENT
    1104: 6.0,   # fg-vm04-FC
    2101: 10.0,  # FAZ-10GB
    2201: 5.0,   # FMG-10device
    3101: 54.0,  # FG-2600F-UTP: four devices total 4 × weekday Cloud cost
    3120: 7.0,   # fg-120G-ENT: near the 6-point VM04 profile
}

def _point_value(current: date, config_id: int) -> float:
    """Use a stable, round daily cost for a configuration and its active VMs."""
    cost = DAILY_CONFIG_POINTS[config_id]
    if config_id in {1101, 1102, 1104}:
        if current.weekday() == 5:  # Saturday
            return cost * 3
        if current.weekday() == 6:  # Sunday
            return cost * 2
    return cost


def seed(profile: str = "demo") -> None:
    """Create/reset a specified Demo profile; live profiles never invoke this."""
    devices = _devices()
    refreshed_at = datetime.now(timezone.utc).isoformat()
    with connect(profile) as connection:
        connection.execute("DELETE FROM usage_day_coverage")
        connection.execute("DELETE FROM usage_records")
        connection.execute("DELETE FROM devices")
        connection.execute("DELETE FROM configurations")
        connection.execute("DELETE FROM departments")
        connection.executemany("INSERT INTO departments(code,display_name,notes) VALUES(?,?,?)", DEPARTMENTS)
        connection.executemany(
            "INSERT INTO configurations(config_id,product,config_name,features,status,notes,refreshed_at) VALUES(?,?,?,?,?,?,?)",
            [
                (config_id, product, name, json.dumps({"parameters": [{"name": key, "value": value} for key, value in parameters]}), status, "", refreshed_at)
                for config_id, product, name, status, parameters in CONFIGURATIONS
            ],
        )
        connection.executemany(
            "INSERT INTO devices(serial,friendly_name,department_code,notes,product,portal_name,entitlement_status,config_id,entitlement_start_date,entitlement_end_date) VALUES(?,?,?,?,?,?,?,?,?,?)",
            devices,
        )
        start = date.today() - timedelta(days=150)
        # Whole-profile gaps demonstrate that a missing reading remains missing
        # in charts and cache coverage; it is never converted to zero points.
        missing_dates = {date.today() - timedelta(days=offset) for offset in (45, 61, 78)}
        points = []
        for device in devices:
            serial, _name, _department, _note, _product, _portal_name, status, config_id, *_dates = device
            for day_index in range(150):
                current = start + timedelta(days=day_index)
                if current in missing_dates:
                    continue
                # Pending/stopped demo entitlements use a real zero, distinct
                # from an absent reading.
                value = 0.0 if status in {"PENDING", "STOPPED"} else _point_value(current, config_id)
                points.append((serial, current.isoformat(), value, "sample", refreshed_at))
        connection.executemany("INSERT INTO usage_records VALUES(?,?,?,?,?)", points)
        connection.execute("UPDATE refresh_state SET status='ready',message='Fabricated Demo inventory loaded',refreshed_at=? WHERE id=1", (refreshed_at,))


if __name__ == "__main__":
    seed()
