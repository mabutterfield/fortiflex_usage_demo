# FortiFlex departmental usage

A local Docker dashboard for viewing FortiFlex point usage by department and
entitlement. It stores a small local SQLite cache per FortiFlex program so
department mapping, notes, filtering, and charts remain fast and never require
a Fortinet request.

It is a read-only reporting aid, not a production billing or entitlement
management system.

## Start the dashboard and create a Demo profile

```sh
cp .env.example .env
docker compose up --build
```

Starting the container does **not** create a sample database. Open
`http://127.0.0.1:8088`, choose **New profile**, then choose **Demo
environment** and give it a name. That creates a Demo database from the
tracked seed definition, with fake devices, departments, and historical daily
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
profile uses `demo/<PROGRAM_SERIAL>.db` and has one saved FortiFlex account.
Create a separate profile for another account or program.

`demo/connection.json` is a mode-0600 local registry, shaped like this:

```json
{
  "version": 1,
  "profiles": {
    "PROGRAM_SERIAL": {
      "program_serial": "PROGRAM_SERIAL",
      "database": "PROGRAM_SERIAL.db",
      "connection": {"account_id": 123, "username": "...", "password": "..."}
    }
  }
}
```

Program serials are validated to letters, numbers, `_`, and `-`. Existing
connection registries are migrated automatically on startup; a legacy
multi-account profile retains the account that the prior UI displayed.

### Credential storage reminder

The saved API password is **plaintext** in the local `demo/connection.json`
file. Its `0600` mode limits normal same-host access, but it does not encrypt
the file. Keep `demo/` private, never commit or share it, and keep the
dashboard bound to localhost unless you intentionally secure it. For a more
secure future deployment, use an OS credential store (macOS Keychain, Windows
Credential Manager, or a Linux Secret Service) or a platform-managed secret
mount. An external vault integration is intentionally outside this demo's
scope.

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
- **Populate catalog** updates FortiFlex-owned inventory and configuration
  values in one action, while preserving locally assigned department codes and
  device/configuration notes.
- **Pull week** checks the last seven complete calendar days (yesterday
  backwards) and retrieves only dates missing from that window. **Pull full
  data** rereads the rolling 90 complete days. The current day is always
  excluded so a partial day is never presented as a daily total.
- Each daily request covers every entitlement returned for the account/program.
  Department selection, inventory filtering, and device charts are therefore
  instant local-cache views and never produce a Fortinet request.
- The green/red calendar is the cache-reading ledger for the current profile:
  green means its saved FortiFlex account was retrieved successfully on that
  date. Red means that profile's date can be polled later. It is not a claim
  that a device consumed zero points.
- Pulls run in the background and wait one second between account-day requests
  (about 60/minute, below the documented 100/minute limit). A one-account
  90-day pull normally takes about 90 seconds plus API latency.

## What the screens mean

- **Department chart:** Choose a department and display range (7, 30, or 90
  complete days, or the prior calendar month). The chart and point total are
  calculated immediately from the local cache. Hover a bar for its date and
  value.
- **Missed readings:** Shown in red only when the selected range has cache
  gaps. It is a missing profile-day cache reading, not a statement that points
  were zero.
  The reading calendar provides the longer historical view: green is cached,
  red can still be retrieved, and grey is outside the 90-day retrieval window.
- **Device inventory:** Filters are local-only. By default it shows ACTIVE and
  PENDING entitlements; filters can also narrow by department, product, and
  Config ID. Clicking a serial opens its bar chart; clicking its Config ID moves
  to the matching configuration record.
- **Configuration inventory:** `Name` is the configuration label supplied by
  FortiFlex. `Profile` is a concise local display
  summary derived from the cached parameters (for example, `1 vCPU · FortiCare
  only` or `10 GB/day · Support + 3 add-ons`). It is not an official SKU.
  Only configuration Notes are editable locally.
- **Department inventory:** Department `Code` is the stable assignment value;
  its display name and notes are local chargeback metadata.

## Current capabilities

- Department and device daily bar charts with hover values; 7/30/90-day and
  prior-month views; local device/configuration/department inventory filters;
  cache calendar with local single-date/range deletion (FortiFlex is never
  changed); CSV device export; and a downloadable JSON rollup for the
  displayed period and department scope.
- Per-profile SQLite cache with one saved account, and a configuration catalogue
  that links entitlement Config IDs to product, portal
  configuration name, concise profile summary, status, and local notes.
- **Pull config prices** calculates the current daily points for cached ACTIVE
  configurations only. It never refreshes the catalogue first; use Populate
  catalog when the cached configuration definition needs updating.
- **How configuration pricing works:** A configuration's FortiFlex Config ID
  identifies the local catalogue row and links devices back to it; it is *not*
  sent to the points calculator. For each cached ACTIVE configuration, the app
  maps its product to a calculator product type, sends the program serial,
  `count: 1`, and the complete cached parameter list, then saves the returned
  `current`, `latest`, and `latestEffectiveDate` values on that same local
  Config ID row. 
- Sample-mode refresh and idempotent SQLite records keyed by serial/date.
- Web API setup route and CLI use the same input validation. Credentials are
  saved only server-side in plaintext `demo/connection.json` with restricted
  permissions; API responses never return passwords.
- **API Log** is a right-side debug tray on live profiles. It retains one
  in-memory response each for entitlement inventory, configuration catalogue,
  daily points, calculator metadata, and configuration pricing calls. Live
  response lists are limited to five real `records`; they are not fabricated.
  OAuth/login requests are excluded, and passwords, tokens, authorization
  values, and similarly named fields are recursively redacted before a response
  reaches the browser. Entries disappear when the app restarts. **API Sample**
  is available on every profile and shows clearly fabricated, safe sample calls;
  Demo profiles show only that button.
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
