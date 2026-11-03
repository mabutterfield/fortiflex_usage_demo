from __future__ import annotations
import sys
from datetime import date, timedelta
from .db import connect

DEVICES = [
 ("FGT-A1B2C3", "edge-east-01", "NETWORK", "Primary east perimeter", "FortiGate VM"),
 ("FGT-D4E5F6", "edge-west-01", "NETWORK", "Primary west perimeter", "FortiGate VM"),
 ("FAZ-G7H8I9", "analytics-01", "SECOPS", "Central logging", "FortiAnalyzer VM"),
 ("FCT-J1K2L3", "ems-lab-01", "WORKPLACE", "Endpoint management", "FortiClient EMS"),
 ("FWEB-M4N5O6", "apps-private-01", "APPS", "Internal application firewall", "FortiWeb VM"),
]

def seed() -> None:
    with connect() as c:
        c.execute("DELETE FROM usage_records"); c.execute("DELETE FROM devices")
        c.executemany("INSERT INTO devices(serial,friendly_name,department_code,notes,product) VALUES(?,?,?,?,?)", DEVICES)
        start = date.today().replace(day=1) - timedelta(days=150)
        rows = []
        for serial_index, (serial, *_rest) in enumerate(DEVICES):
            for day in range(150):
                current = start + timedelta(days=day)
                # A deliberate missing reading is represented by NULL, not zero.
                points = None if serial == "FCT-J1K2L3" and day in (20, 70) else round((serial_index + 1) * 0.55 + (day % 8) * 0.14, 2)
                rows.append((serial, current.isoformat(), points, "sample", current.isoformat() + "T06:00:00Z"))
        c.executemany("INSERT INTO usage_records VALUES(?,?,?,?,?)", rows)

if __name__ == "__main__":
    seed()
