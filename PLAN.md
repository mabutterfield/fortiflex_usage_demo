# Implementation notes and follow-up work

## Scope and architecture

The application is one Docker Compose service: a FastAPI application serving
its web UI and a per-profile SQLite database on the mounted `demo/` volume. Default publishing is
`127.0.0.1:8088`, with address/port configurable in Compose. TLS is optional via
mounted PEM certificate/key paths. Credentials live in a mode-0600 local file or
are sourced from environment variables/mounted secrets; none, certificates, or
runtime data are committed.

## Implemented

Implemented so far:

1. Docker Compose, FastAPI web UI, SQLite migrations, sample data, profile
   registry, and server-side-only credential storage.
2. Current-state device department mapping and notes, daily serial cache,
   cache-coverage tracking, local charts, filters, CSV export, and reading
   calendar.
3. Read-only live inventory, point, and configuration-catalogue pulls. A
   configuration includes the FortiFlex name separately from its concise local
   profile summary.
4. One program can contain multiple saved FortiFlex accounts. Inventory and
   configuration pulls preserve local notes and department mapping.

## Confirmed integration behavior

The authenticated FNDN reference (reviewed 2026-11-02) confirms:

- base URL `https://support.fortinet.com/ES/api/fortiflex/v2/` and OAuth password
  grant at `https://customerapiauth.fortinet.com/api/v1/oauth/token/` with
  `client_id=flexvm`;
- `POST /entitlements/points` accepts either `configId`, or the
  `accountId` + `programSerialNumber` pair, plus `startDate` and `endDate`;
- the response contains a single `points` total per entitlement serial, not
  dated observations;
- consumption older than 90 days is excluded from results; and
- limits are 100 calls/minute and 1,000 calls/hour.

The lab profile verified a read-only request and recorded:

- inclusive/exclusive date boundaries and timezone;
- whether one-day query windows give a reliable daily value;
- maximum historical range, retention, pagination, and request/rate limits;
- OAuth grant, expiry/refresh behavior, error responses, and required IAM role;
- a safe, non-destructive connection-test request.

Live reporting is limited to the rolling 90-day retrieval window unless the
local database retains snapshots from earlier pulls. Credentials must never be
retained in source, logs, or a commit.

### Lab verification (2026-11-02)

OAuth authentication succeeded with the saved lab profile. The points endpoint
also accepted both a two-day and a same-day date range and returned successful
responses containing entitlement `serialNumber`, `accountId`, and aggregate
`points` only. It did not include date-bearing records. Treat same-day requests
as a viable polling mechanism, pending confirmation of the API's timezone and
inclusive/exclusive boundary behavior before calling those results daily usage.

## Follow-up work

1. Add comprehensive automated tests for pull pacing, missing-vs-zero coverage,
   configuration parsing, inventory filters, and profile migrations.
2. Confirm the Fortinet timezone and same-day boundary semantics before treating
   daily polling as a billing-grade record.
3. Add durable background-job state and retry/backoff if this moves beyond a
   single-user local tool.
4. Consider a real SKU/catalogue mapping only if official Fortinet source data
   is available; the current Profile column is intentionally a concise display
   summary, not a SKU.
5. Keep the scope read-only: this application does not alter running devices or
   FortiFlex entitlements.
