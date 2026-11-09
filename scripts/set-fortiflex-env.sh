#!/usr/bin/env bash
# Source this file so its exports remain in the calling shell:
#   source scripts/set-fortiflex-env.sh

if [[ -n "${BASH_VERSION:-}" && "${BASH_SOURCE[0]}" == "$0" ]] || \
   [[ -n "${ZSH_VERSION:-}" && "${ZSH_EVAL_CONTEXT:-}" != *:file ]]; then
  echo "Source this helper instead: source scripts/set-fortiflex-env.sh" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to safely create FORTIFLEX_CONNECTIONS_JSON." >&2
  return 1
fi

printf 'FortiFlex program serial: '
IFS= read -r FORTIFLEX_PROGRAM_SERIAL
printf 'FortiCloud account ID: '
IFS= read -r FORTIFLEX_ACCOUNT_ID
printf 'FortiFlex API username: '
IFS= read -r FORTIFLEX_USERNAME
printf 'FortiFlex API password: '
IFS= read -r -s FORTIFLEX_PASSWORD
printf '\n'

if [[ ! "$FORTIFLEX_ACCOUNT_ID" =~ ^[1-9][0-9]*$ ]]; then
  echo "Account ID must be a positive integer." >&2
  return 1
fi
if [[ ! "$FORTIFLEX_PROGRAM_SERIAL" =~ ^[A-Za-z0-9_-]{3,128}$ ]]; then
  echo "Program serial must use 3-128 letters, numbers, _ or -." >&2
  return 1
fi

selected_profile="$FORTIFLEX_PROGRAM_SERIAL"

export FORTIFLEX_PROGRAM_SERIAL FORTIFLEX_ACCOUNT_ID FORTIFLEX_USERNAME FORTIFLEX_PASSWORD
export FORTIFLEX_CONNECTIONS_JSON
FORTIFLEX_CONNECTIONS_JSON="$(python3 -c '
import json, os
program = os.environ["FORTIFLEX_PROGRAM_SERIAL"]
print(json.dumps({program: {
    "account_id": int(os.environ["FORTIFLEX_ACCOUNT_ID"]),
    "username": os.environ["FORTIFLEX_USERNAME"],
    "password": os.environ["FORTIFLEX_PASSWORD"],
    "program_serial": program,
}}))
')"
unset FORTIFLEX_ACCOUNT_ID FORTIFLEX_USERNAME FORTIFLEX_PASSWORD FORTIFLEX_PROGRAM_SERIAL

echo "FORTIFLEX_CONNECTIONS_JSON is set for ${selected_profile}."
echo "Create or select that program profile, then run: docker compose up -d"
