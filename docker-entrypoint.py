"""Initialise a persistent demo database, then launch FastAPI."""
import os
import shutil
import sys
from pathlib import Path

db_path = Path(os.environ.get("APP_DB_PATH", "/app/demo/demo.db"))
template = Path("/app/template/demo_template.db")
db_path.parent.mkdir(parents=True, exist_ok=True)
if os.environ.get("SAMPLE_MODE", "true").lower() == "true":
    for database in (db_path, db_path.parent / "demo.db"):
        if not database.exists():
            shutil.copy2(template, database)

args = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
cert, key = os.environ.get("TLS_CERT_FILE"), os.environ.get("TLS_KEY_FILE")
if bool(cert) != bool(key):
    raise SystemExit("TLS_CERT_FILE and TLS_KEY_FILE must be set together")
if cert and key:
    args += ["--ssl-certfile", cert, "--ssl-keyfile", key]
os.execvp(args[0], args)
