"""Small, read-only FortiFlex client. Tokens never leave this module."""
from __future__ import annotations
import json
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .config import ConnectionInput

AUTH_URL = "https://customerapiauth.fortinet.com/api/v1/oauth/token/"
API_BASE = "https://support.fortinet.com/ES/api/fortiflex/v2"

class FortiFlexError(RuntimeError): pass

def _request(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST"), timeout=20) as response:
            return json.loads(response.read())
    except HTTPError as error:
        raise FortiFlexError(f"Fortinet returned HTTP {error.code}") from error
    except URLError as error:
        raise FortiFlexError("Could not reach Fortinet") from error

def token(connection: ConnectionInput) -> str:
    result = _request(AUTH_URL, {"username": connection.username, "password": connection.password, "client_id": "flexvm", "grant_type": "password"})
    if not result.get("access_token"): raise FortiFlexError("Authentication response did not contain an access token")
    return result["access_token"]

def list_entitlements(connection: ConnectionInput, capture: Callable[[str, dict, dict], None] | None = None) -> list[dict]:
    payload = {"accountId": connection.account_id, "programSerialNumber": connection.program_serial}
    result = _request(f"{API_BASE}/entitlements/list", payload, token(connection))
    if result.get("status") != 0: raise FortiFlexError("FortiFlex did not accept the entitlement-list request")
    if capture: capture("/entitlements/list", payload, result)
    # Return only inventory fields; API tokens are intentionally discarded.
    allowed = {"serialNumber", "description", "configId", "accountId", "startDate", "endDate", "status", "tokenStatus", "followProgram"}
    return [{key: value for key, value in item.items() if key in allowed} for item in result.get("entitlements", [])]

def daily_points(connection: ConnectionInput, usage_date: str, access_token: str, capture: Callable[[str, dict, dict], None] | None = None) -> list[dict]:
    """Retrieve a single complete calendar day's points for one account.

    FortiFlex returns one aggregate per entitlement for a requested window.  The
    caller deliberately supplies a one-day window so it can keep a local daily
    history.  Only serial and points cross this boundary; bearer tokens do not.
    """
    payload = {
        "accountId": connection.account_id,
        "programSerialNumber": connection.program_serial,
        "startDate": usage_date,
        "endDate": usage_date,
    }
    result = _request(f"{API_BASE}/entitlements/points", payload, access_token)
    if result.get("status") not in (0, None):
        raise FortiFlexError("FortiFlex did not accept the points request")
    if capture: capture("/entitlements/points", payload, result)
    # API documentation and lab responses have used an entitlements collection.
    # Accept the documented shape and two harmless wrapper variants defensively.
    items = result.get("entitlements") or result.get("points") or result.get("data") or []
    if not isinstance(items, list):
        raise FortiFlexError("Unexpected points response format")
    return [
        {"serial": item.get("serialNumber") or item.get("serial"), "points": item.get("points")}
        for item in items if isinstance(item, dict) and (item.get("serialNumber") or item.get("serial"))
    ]

def list_configurations(connection: ConnectionInput, capture: Callable[[str, dict, dict], None] | None = None) -> list[dict]:
    """Read the program's configuration catalogue without retaining secrets."""
    payload = {"accountId": connection.account_id, "programSerialNumber": connection.program_serial}
    result = _request(f"{API_BASE}/configs/list", payload, token(connection))
    if result.get("status") not in (0, None):
        raise FortiFlexError("FortiFlex did not accept the configuration-list request")
    if capture: capture("/configs/list", payload, result)
    items = result.get("configurations") or result.get("configs") or result.get("data") or []
    if isinstance(items, dict):
        # The current list API groups records by product family (for example
        # fgt_vm and fwb_vm), rather than returning one flat collection.
        items = [dict(item, _product_family=family) for family, group in items.items() for item in (group if isinstance(group, list) else []) if isinstance(item, dict)]
    if not isinstance(items, list):
        raise FortiFlexError("Unexpected configuration-list response format")
    safe = []
    for item in items:
        if not isinstance(item, dict):
            continue
        config_id = item.get("configId") or item.get("configurationId") or item.get("id")
        if config_id is None:
            continue
        # Product and services describe the configuration; omit any fields
        # which could contain a token, secret, or credentials.
        product_value = item.get("productType") or item.get("productName") or item.get("product") or item.get("_product_family") or ""
        product = product_value.get("name") if isinstance(product_value, dict) else product_value
        # Product-specific configuration fields vary widely (FortiGate capacity,
        # FortiWeb throughput, service bundles, and so on). Preserve every
        # non-sensitive field we do not already display as a dedicated column.
        excluded = {"configId", "configurationId", "id", "name", "status", "product", "productType", "productName", "_product_family", "accountId", "programSerialNumber"}
        features = {
            key: value for key, value in item.items()
            if key not in excluded and not any(word in key.lower() for word in ("token", "secret", "password", "credential"))
        }
        safe.append({
            "config_id": int(config_id),
            "product": str(product or ""),
            "config_name": str(item.get("name") or ""),
            "status": str(item.get("status") or ""),
            "features": features,
        })
    return safe


def pricing_metadata(connection: ConnectionInput, access_token: str, capture: Callable[[str, dict, dict], None] | None = None) -> list[dict]:
    """Return calculator metadata needed to map cached configurations safely."""
    result = _request(f"{API_BASE}/tools/metadata", {}, access_token)
    if capture:
        capture("/tools/metadata", {}, result)
    if result.get("status") not in (0, None):
        raise FortiFlexError(result.get("message") or "FortiFlex did not accept the pricing metadata request")
    items = result.get("productTypes") or []
    if not isinstance(items, list):
        raise FortiFlexError("Unexpected pricing metadata response format")
    return [item for item in items if isinstance(item, dict)]


def calculate_points(connection: ConnectionInput, access_token: str, product_type_id: int, parameters: list[dict], capture: Callable[[str, dict, dict], None] | None = None) -> dict:
    """Calculate one cached configuration's per-instance daily point price."""
    payload = {
        "programSerialNumber": connection.program_serial,
        "count": 1,
        "productTypeId": product_type_id,
        "parameters": parameters,
    }
    result = _request(f"{API_BASE}/tools/calc", payload, access_token)
    if capture:
        capture("/tools/calc", payload, result)
    if result.get("status") not in (0, None):
        raise FortiFlexError(result.get("message") or "FortiFlex did not accept the pricing request")
    # The calculator response is named `configs` in the current API, while
    # older documentation/examples show `points` or a `data.points` wrapper.
    # Accept all known shapes without inventing a value when none is returned.
    data = result.get("data")
    points = result.get("points") or result.get("configs")
    if not isinstance(points, dict) and isinstance(data, dict):
        points = data.get("points") or data
    if not isinstance(points, dict) or points.get("current") is None:
        raise FortiFlexError("Unexpected pricing response format")
    return points
