# FortiFlex departmental usage

A local Docker dashboard for viewing FortiFlex point usage by department and
entitlement. It stores a small local SQLite cache per FortiFlex program so
department mapping, notes, filtering, and charts remain fast and never require
a Fortinet request.

It is a read-only reporting aid, not a production billing or entitlement
management system.

## Run the sample demo

```sh
cp .env.example .env
docker compose up --build
```

Open `http://127.0.0.1:8088`, choose **New profile**, then choose **Demo
environment**. It uses fake devices, departments, and historical daily
readings. Intentional gaps demonstrate that missing data is never shown as
zero.

Three whole-profile reading gaps at 45, 61, and 78 days ago are included so the
90-day display and reading calendar can demonstrate missing-data behavior.

The fabricated inventory contains 32 entitlements: eighteen FortiGate VMs in
Cloud, four Core and six R&D hardware FortiGates, and two each of
FortiAnalyzer and FortiManager in SharedInfra. Its seven configuration profiles
are deliberately invented examples, not copies of a live FortiFlex catalogue.

Demo environments are generated from the tracked seed definition when created
or reset. The `demo/` directory is mounted as one volume and ignored by Git.

## Profiles and local storage

The top-bar **Profile** selector contains only profiles you created. A program
profile uses `demo/<PROGRAM_SERIAL>.db`; saving a different account for the
same program adds an account to that profile rather than overwriting the first.

`demo/connection.json` is a mode-0600 local registry, shaped like this (passwords
are present only on disk and are omitted here):

```json
{
  "version": 1,
  "profiles": {
    "PROGRAM_SERIAL": {
      "program_serial": "PROGRAM_SERIAL",
      "database": "PROGRAM_SERIAL.db",
      "accounts": [{"account_id": 123, "username": "...", "password": "..."}]
    }
  }
}
```

Program serials are validated to letters, numbers, `_`, and `-`. Existing
single-account `connection.json` files are migrated automatically on startup.

Use **New profile** in the Profile controls to create either an empty
FortiFlex-program profile (then use Edit connection) or a named Demo
environment. The latter is generated from the tracked
[`app/seed.py`](app/seed.py) definition, stays in sample mode, and is useful
for a disposable walkthrough. Generated SQLite databases remain local and are
ignored by Git.

## Dashboard and local cache

The dashboard intentionally separates **viewing** cached data from **pulling**
new data:

- Profile controls are context-sensitive: Demo profiles offer **Reset demo
  database** and **Reading calendar**; program profiles offer **Edit
  connection**, **Test connection**, catalog population, daily pulls, and the
  reading calendar. Editing only saves local credentials; testing only performs
  OAuth validation.
- Inventory population updates FortiFlex-owned values (serial, portal name,
  entitlement status, dates, and Config ID), while preserving locally assigned
  department codes and device notes. Configuration population similarly keeps
  local configuration notes.
- Pull week retrieves at most seven missing *complete* calendar days, newest
  first. Pull full data rereads the rolling 90 complete days. The current day is
  always excluded so a partial day is never presented as a daily total.
- Each daily request covers every entitlement returned for the account/program.
  Department selection, inventory filtering, and device charts are therefore
  instant local-cache views and never produce a Fortinet request.
- The green/red calendar is the cache-reading ledger for the profile: green
  means data is cached; for current pulls, its coverage record means every
  configured account was retrieved successfully on that date. Red means the
  date can be polled later. It is not a claim that a device consumed zero
  points.
- Pulls run in the background and wait one second between account-day requests
  (about 60/minute, below the documented 100/minute limit). A one-account
  90-day pull normally takes about 90 seconds plus API latency.

## What the screens mean

- **Department chart:** Choose a department and display range (7, 30, or 90
  complete days, or the prior calendar month). The chart and point total are
  calculated immediately from the local cache. Hover a bar for its date and
  value.
- **Missed readings:** Shown only when the selected range has cache gaps. It is
  a missing account-day cache reading, not a statement that points were zero.
  The reading calendar provides the longer historical view: green is cached,
  red can still be retrieved, and grey is outside the 90-day retrieval window.
- **Device inventory:** Filters are local-only. By default it shows ACTIVE and
  PENDING entitlements; filters can also narrow by department, product, and
  Config ID. Clicking a serial opens its bar chart; clicking its Config ID moves
  to the matching configuration record.
- **Configuration inventory:** `Name` is the configuration label supplied by
  FortiFlex (for example, `fg-vm01-FC_tf`). `Profile` is a concise local display
  summary derived from the cached parameters (for example, `1 vCPU · FortiCare
  only` or `10 GB/day · Support + 3 add-ons`). It is not an official SKU.
  Only configuration Notes are editable locally.
- **Department inventory:** Department `Code` is the stable assignment value;
  its display name and notes are local chargeback metadata.

## Current capabilities

- Department and device daily bar charts with hover values; 7/30/90-day and
  prior-month views; local device/configuration/department inventory filters;
  cache calendar; CSV device export; and a downloadable JSON rollup for the
  displayed period and department scope.
- Per-program SQLite cache, multiple saved accounts for one program, and a
  configuration catalogue that links entitlement Config IDs to product, portal
  configuration name, concise profile summary, status, and local notes.
- Sample-mode refresh and idempotent SQLite records keyed by serial/date.
- Web API setup route and CLI use the same input validation. Credentials are
  saved only server-side in `demo/connection.json` with restricted permissions;
  API responses never return passwords.
- `python -m app.cli init-sample`, `status`, `setup`, and `clear-connection`
  offer the corresponding local CLI operations (run within the container, or
  in a Python environment with `requirements.txt` installed).
- Optional TLS: set both `TLS_CERT_FILE` and `TLS_KEY_FILE` to mounted paths.

## Live FortiFlex behavior

The authenticated API reference and lab verification confirm that the points
endpoint returns a total by serial for a requested date window, excludes data
older than 90 days, and is subject to 100/minute and 1,000/hour limits. The
dashboard makes single-day requests and retains successful coverage separately
from reported points. Never commit credentials, certificates, or databases.

## Development checks

```sh
python -m pip install -r requirements-dev.txt
pytest -q
```

Known limitations and follow-up work are documented in [PLAN.md](PLAN.md).
