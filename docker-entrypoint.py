"""Initialise a persistent demo database, then launch FastAPI."""
import os
import sys

args = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
cert, key = os.environ.get("TLS_CERT_FILE"), os.environ.get("TLS_KEY_FILE")
if bool(cert) != bool(key):
    raise SystemExit("TLS_CERT_FILE and TLS_KEY_FILE must be set together")
if cert and key:
    args += ["--ssl-certfile", cert, "--ssl-keyfile", key]
os.execvp(args[0], args)
