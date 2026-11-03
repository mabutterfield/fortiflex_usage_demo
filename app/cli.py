from __future__ import annotations
import argparse, getpass
from .config import ConnectionInput, clear_connection, connection_summary, save_connection
from .seed import seed

def main():
    parser=argparse.ArgumentParser(description="FortiFlex chargeback demo CLI")
    sub=parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-sample", help="create/reset sample database")
    sub.add_parser("status", help="show connection status without secrets")
    sub.add_parser("clear-connection", help="remove server-side credentials")
    sub.add_parser("setup", help="save a FortiFlex connection")
    a=parser.parse_args()
    if a.command=="init-sample": seed(); print("Sample data initialised")
    elif a.command=="status": print(connection_summary())
    elif a.command=="clear-connection": clear_connection(); print("Connection cleared")
    else:
        data=ConnectionInput(account_id=int(input("FortiCloud account ID: ")),username=input("API username: "),password=getpass.getpass("API password: "),program_serial=input("FortiFlex program serial: "))
        save_connection(data); print("Connection saved. Live test remains disabled pending API behavior verification.")
if __name__ == "__main__": main()
