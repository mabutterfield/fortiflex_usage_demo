from __future__ import annotations
import calendar, csv, io, json, os, threading, time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .config import ConnectionInput, clear_connection, connection_summary, create_profile, delete_profile, is_sample_profile, list_profiles, save_connection, stored_connection
from .db import connect
from .debug import demo_samples, record as record_api_sample, samples as api_samples
from .fortiflex import FortiFlexError, calculate_points, daily_points, list_configurations, list_entitlements, pricing_metadata, token
from .seed import seed

app = FastAPI(title="FortiFlex departmental chargeback demo")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
PULL_LOCK = threading.Lock()
PULL_JOBS: dict[str, dict] = {}

def days_back(count: int) -> list[str]:
    end = date.today() - timedelta(days=1)
    return [(end-timedelta(days=i)).isoformat() for i in range(count-1,-1,-1)]
def view_days(view: str) -> list[str]:
    if view in ("7", "30", "90"):
        return days_back(int(view))
    if view == "last_month":
        first_this_month = date.today().replace(day=1)
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
        return [(start + timedelta(days=offset)).isoformat() for offset in range((end-start).days+1)]
    raise HTTPException(400, "Unknown display range")

def coverage(profile: str, days: list[str]) -> list[dict]:
    account = stored_connection(profile)
    if not days: return []
    with connect(profile) as c:
        if is_sample_profile(profile):
            expected = c.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
            rows = c.execute("SELECT usage_date,COUNT(DISTINCT serial) count FROM usage_records WHERE usage_date IN (%s) GROUP BY usage_date" % ",".join("?"*len(days)),days).fetchall()
            found = {r["usage_date"]: r["count"] for r in rows}
            return [{"usage_date": d, "complete": expected > 0 and found.get(d, 0) >= expected} for d in days]
        rows = c.execute("SELECT usage_date,COUNT(*) count FROM usage_day_coverage WHERE status='complete' AND usage_date IN (%s) GROUP BY usage_date" % ",".join("?"*len(days)),days).fetchall()
    found, expected = {r["usage_date"]:r["count"] for r in rows},int(account is not None)
    return [{"usage_date":d,"complete":expected>0 and found.get(d,0)>=expected} for d in days]

def series(profile: str, days: list[str], department: str|None=None, serial: str|None=None) -> list[dict]:
    if not days:return []
    parts,args=["u.usage_date IN (%s)" % ",".join("?"*len(days))],list(days)
    if department: parts.append("d.department_code=?");args.append(department)
    if serial: parts.append("d.serial=?");args.append(serial)
    with connect(profile) as c:
        rows=c.execute("SELECT u.usage_date,ROUND(SUM(u.points),2) points FROM usage_records u JOIN devices d ON d.serial=u.serial WHERE %s GROUP BY u.usage_date" % " AND ".join(parts),args).fetchall()
    values={r["usage_date"]:r["points"] for r in rows}
    return [{"usage_date":d,"points":values.get(d)} for d in days]

def department_rollup(profile: str, days: list[str], department: str="") -> list[dict]:
    """Summarise locally cached points by department for an export period."""
    if not days:
        return []
    clause, extra = (" WHERE department.code=?", [department]) if department else ("", [])
    placeholders = ",".join("?" * len(days))
    query = """SELECT department.code,department.display_name,
        ROUND(COALESCE(SUM(usage.points),0),2) AS points
        FROM departments department
        LEFT JOIN devices device ON device.department_code=department.code
        LEFT JOIN usage_records usage ON usage.serial=device.serial
            AND usage.usage_date IN (%s)
        %s GROUP BY department.code,department.display_name ORDER BY department.code""" % (placeholders, clause)
    with connect(profile) as c:
        return [dict(row) for row in c.execute(query, [*days, *extra])]

@app.get("/api/profiles")
def profiles(): return list_profiles()
class ProfileCreate(BaseModel):
    profile: str
    source: str
@app.post("/api/profiles")
def new_profile(request: ProfileCreate):
    try:
        created = create_profile(request.profile.strip(), request.source)
        if request.source == "demo":
            seed(created["id"])
        return created
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
@app.delete("/api/profiles/{profile}")
def remove_profile(profile: str):
    try:
        delete_profile(profile)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True}
@app.post("/api/profiles/{profile}/reset-demo")
def reset_demo_profile(profile: str):
    if not is_sample_profile(profile):
        raise HTTPException(400, "Only Demo profiles can be reset")
    seed(profile)
    return {"ok": True, "message": "Demo database reset"}
@app.get("/api/status")
def status(profile: str="demo"):
    with connect(profile) as c: row=c.execute("SELECT status,message,refreshed_at FROM refresh_state WHERE id=1").fetchone()
    return {"profile":profile,"sample_mode":is_sample_profile(profile),"connection":connection_summary(profile),"refresh":dict(row),"pull":PULL_JOBS.get(profile)}
@app.get("/api/debug/log")
def debug_log(profile: str="demo"):
    return {"samples": api_samples(profile)}
@app.get("/api/debug/sample")
def debug_sample():
    return {"samples": demo_samples()}
@app.get("/api/departments")
def departments(profile: str="demo"):
    with connect(profile) as c:return [dict(r) for r in c.execute("SELECT d.*,COUNT(v.serial) entitlement_count FROM departments d LEFT JOIN devices v ON v.department_code=d.code GROUP BY d.code ORDER BY d.code")]
@app.get("/api/dashboard")
def dashboard(profile: str="demo",department: str="",view: str="30"):
    days=view_days(view)
    marks=coverage(profile,days)
    return {"points":round(sum(r["points"] or 0 for r in series(profile,days,department or None)),2),"missing_readings":sum(1 for mark in marks if not mark["complete"]),"coverage":marks,"series":series(profile,days,department or None),"view":view,"from":days[0],"to":days[-1]}
@app.get("/api/coverage")
def coverage_month(profile: str="demo", month: str=""):
    try:
        year, number = (int(value) for value in month.split("-", 1))
        start = date(year, number, 1)
    except Exception as error:
        raise HTTPException(400, "Month must be YYYY-MM") from error
    end = date(year, number, calendar.monthrange(year, number)[1])
    with connect(profile) as c:
        starts = [row[0] for row in c.execute("SELECT entitlement_start_date FROM devices WHERE entitlement_start_date IS NOT NULL UNION SELECT MIN(usage_date) FROM usage_records").fetchall() if row[0]]
        cached = {row[0] for row in c.execute("SELECT DISTINCT usage_date FROM usage_records WHERE usage_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat()))}
    data_start = min(starts) if starts else None
    days = [(start + timedelta(days=offset)).isoformat() for offset in range((end-start).days+1)]
    covered = {item["usage_date"]: item["complete"] for item in coverage(profile, days)}
    retention_start = date.today() - timedelta(days=90)
    readings = []
    for day in days:
        current = date.fromisoformat(day)
        if current > date.today() - timedelta(days=1): state = "future"
        elif data_start and day < data_start: state = "before_start"
        elif covered.get(day) or day in cached: state = "complete"
        elif current < retention_start: state = "outside_retention"
        else: state = "missing"
        readings.append({"usage_date":day,"state":state})
    return {"month":month,"data_start":data_start,"days":readings}


class UsageDateDelete(BaseModel):
    start_date: date
    end_date: date


@app.post("/api/usage/dates/delete")
def delete_usage_dates(request: UsageDateDelete, profile: str = "demo"):
    """Delete a local cached usage range only; FortiFlex is never changed."""
    if request.end_date < request.start_date:
        raise HTTPException(400, "End date must be on or after start date")
    start, end = request.start_date.isoformat(), request.end_date.isoformat()
    with connect(profile) as c:
        usage_deleted = c.execute(
            "DELETE FROM usage_records WHERE usage_date BETWEEN ? AND ?", (start, end)
        ).rowcount
        coverage_deleted = c.execute(
            "DELETE FROM usage_day_coverage WHERE usage_date BETWEEN ? AND ?", (start, end)
        ).rowcount
        c.execute(
            "UPDATE refresh_state SET status='ready', message=?, refreshed_at=? WHERE id=1",
            (f"Deleted local cache for {start} through {end}", datetime.now(timezone.utc).isoformat()),
        )
    return {
        "ok": True,
        "start_date": start,
        "end_date": end,
        "usage_records_deleted": usage_deleted,
        "coverage_records_deleted": coverage_deleted,
    }
@app.get("/api/devices")
def devices(profile: str="demo",department: str="",status: str="",config_id: str="",product: str=""):
    where,args=[],[]
    if department: where.append("d.department_code=?");args.append(department)
    states = [value.strip() for value in status.split(",") if value.strip()]
    if states: where.append("d.entitlement_status IN (%s)" % ",".join("?"*len(states)));args.extend(states)
    if config_id: where.append("CAST(d.config_id AS TEXT)=?");args.append(config_id)
    if product: where.append("c.product=?");args.append(product)
    suffix=" WHERE "+" AND ".join(where) if where else ""
    with connect(profile) as c:rows=c.execute("SELECT d.*,c.product AS config_product,c.config_name AS config_name FROM devices d LEFT JOIN configurations c ON c.config_id=d.config_id"+suffix+" ORDER BY d.department_code,d.portal_name,d.serial",args).fetchall()
    return [dict(r) for r in rows]
@app.get("/api/devices/{serial}/usage")
def device_usage(serial: str,profile: str="demo",view: str="30"):return series(profile,view_days(view),serial=serial)
@app.get("/api/configurations")
def configurations(profile: str="demo", product: str="", status: str=""):
    clauses, args = [], []
    if product: clauses.append("product=?"); args.append(product)
    if status: clauses.append("status=?"); args.append(status)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with connect(profile) as c:
        return [dict(row) for row in c.execute("SELECT * FROM configurations"+where+" ORDER BY config_id", args)]


def _pricing_parameters(features: str) -> list[dict]:
    try:
        values = json.loads(features).get("parameters", [])
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    parameters = []
    for value in values:
        if not isinstance(value, dict) or value.get("value") is None:
            continue
        parameter_id = value.get("id") or value.get("parameterId")
        try:
            parameters.append({"id": int(parameter_id), "value": str(value["value"])})
        except (TypeError, ValueError):
            continue
    return parameters


def _pricing_product_type(config: dict, metadata: list[dict]) -> int | None:
    aliases = {
        "fortigatevm": "fortigatevirtualmachine", "fortiwebvm": "fortiwebvirtualmachine",
        "fortimanagervm": "fortimanagervirtualmachine", "fortianalyzervm": "fortianalyzervirtualmachine",
        "fortiadcvm": "fortiadcvirtualmachine", "forticlientems": "forticlientems",
        "fortisoarvm": "fortisoarvirtualmachine", "fortinacvm": "fortinacvirtualmachine",
        "fortiswitchhardware": "fortiswitch",
    }
    family = "".join(character for character in str(config["product"]).lower() if character.isalnum())
    family = aliases.get(family, family)
    try:
        cached_parameters = json.loads(config["features"]).get("parameters", [])
    except (TypeError, ValueError):
        return None
    parameter_names = {
        str(value.get("name", "")).lower() for value in cached_parameters
        if isinstance(value, dict) and value.get("name")
    }
    candidates = []
    for item in metadata:
        try:
            item_id = int(item["productTypeId"])
        except (KeyError, TypeError, ValueError):
            continue
        name = "".join(character for character in str(item.get("name", "")).lower() if character.isalnum())
        if not family or family not in name:
            continue
        metadata_names = {str(value.get("name", "")).lower() for value in item.get("parameters", []) if isinstance(value, dict)}
        candidates.append((len(parameter_names & metadata_names), item_id))
    return max(candidates, default=(-1, None))[1]


@app.post("/api/configurations/prices")
def pull_configuration_prices(profile: str = "demo"):
    """Price only cached ACTIVE configurations; this never refreshes the catalogue."""
    if is_sample_profile(profile):
        raise HTTPException(400, "Demo profiles have fabricated configuration prices")
    account = stored_connection(profile)
    if not account:
        raise HTTPException(400, "No saved account for this profile")
    with connect(profile) as c:
        active = [dict(row) for row in c.execute("SELECT * FROM configurations WHERE UPPER(status)='ACTIVE' ORDER BY config_id")]
    if not active:
        return {"ok": True, "active": 0, "priced": 0, "skipped": 0, "message": "No ACTIVE cached configurations to price."}
    try:
        access_token = token(account)
        metadata = pricing_metadata(account, access_token, lambda endpoint, request, response: record_api_sample(profile, "Pricing metadata", endpoint, request, response))
    except FortiFlexError as error:
        raise HTTPException(502, str(error)) from error
    priced = skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    with connect(profile) as c:
        for config in active:
            parameters = _pricing_parameters(config["features"])
            product_type_id = _pricing_product_type(config, metadata)
            if not parameters or product_type_id is None:
                skipped += 1
                c.execute("UPDATE configurations SET pricing_status=?,priced_at=? WHERE config_id=?", ("Unsupported cached configuration", now, config["config_id"]))
                continue
            try:
                points = calculate_points(account, access_token, product_type_id, parameters, lambda endpoint, request, response: record_api_sample(profile, "Configuration pricing", endpoint, request, response))
                c.execute("UPDATE configurations SET points_per_day=?,latest_points_per_day=?,pricing_effective_date=?,priced_at=?,pricing_status=? WHERE config_id=?", (float(points["current"]), points.get("latest"), points.get("latestEffectiveDate"), now, "Priced", config["config_id"]))
                priced += 1
            except (FortiFlexError, TypeError, ValueError) as error:
                skipped += 1
                c.execute("UPDATE configurations SET pricing_status=?,priced_at=? WHERE config_id=?", (str(error)[:180], now, config["config_id"]))
    return {
        "ok": True,
        "active": len(active),
        "priced": priced,
        "skipped": skipped,
        "message": f"Checked {len(active)} ACTIVE cached configuration(s): priced {priced}; skipped {skipped}.",
    }

class DeviceEdit(BaseModel):department_code:str;notes:str=""
@app.put("/api/devices/{serial}")
def update_device(serial:str,edit:DeviceEdit,profile:str="demo"):
    code=edit.department_code.strip()
    if not code:raise HTTPException(400,"Department code is required")
    with connect(profile) as c:
        if not c.execute("UPDATE devices SET department_code=?,notes=? WHERE serial=?",(code,edit.notes,serial)).rowcount:raise HTTPException(404,"Device not found")
        c.execute("INSERT OR IGNORE INTO departments(code,display_name) VALUES(?,?)",(code,code))
    return {"ok":True}
class DepartmentEdit(BaseModel):code:str;display_name:str;notes:str=""
@app.post("/api/departments")
def create_department(edit: DepartmentEdit, profile: str="demo"):
    code = edit.code.strip()
    if not code:
        raise HTTPException(400, "Department code is required")
    with connect(profile) as c:
        if c.execute("SELECT 1 FROM departments WHERE code=?", (code,)).fetchone():
            raise HTTPException(409, "That department code already exists")
        c.execute("INSERT INTO departments(code,display_name,notes) VALUES(?,?,?)", (code, edit.display_name.strip() or code, edit.notes))
    return {"ok": True, "code": code}
@app.put("/api/departments/{code}")
def save_department(code:str,edit:DepartmentEdit,profile:str="demo"):
    if code!=edit.code or not code.strip():raise HTTPException(400,"Department code is required and cannot be renamed")
    with connect(profile) as c:c.execute("INSERT INTO departments(code,display_name,notes) VALUES(?,?,?) ON CONFLICT(code) DO UPDATE SET display_name=excluded.display_name,notes=excluded.notes",(code,edit.display_name.strip() or code,edit.notes))
    return {"ok":True}
@app.delete("/api/departments/{code}")
def remove_department(code: str, profile: str="demo"):
    with connect(profile) as c:
        assigned = c.execute("SELECT COUNT(*) FROM devices WHERE department_code=?", (code,)).fetchone()[0]
        if assigned:
            raise HTTPException(409, f"Reassign the {assigned} entitlement(s) before deleting this department")
        if not c.execute("DELETE FROM departments WHERE code=?", (code,)).rowcount:
            raise HTTPException(404, "Department not found")
    return {"ok": True}
class ConfigurationEdit(BaseModel):notes:str=""
@app.put("/api/configurations/{config_id}")
def update_configuration(config_id:int,edit:ConfigurationEdit,profile:str="demo"):
    with connect(profile) as c:
        if not c.execute("UPDATE configurations SET notes=? WHERE config_id=?",(edit.notes,config_id)).rowcount:
            raise HTTPException(404,"Configuration not found")
    return {"ok":True}

class ConnectionSave(BaseModel):
    account_id: int
    username: str
    password: str = ""
    program_serial: str
@app.post("/api/setup")
def setup(connection:ConnectionSave):
    password = connection.password
    if not password:
        saved = stored_connection(connection.program_serial)
        if saved and saved.account_id == connection.account_id and saved.username == connection.username:
            password = saved.password
    try:
        validated = ConnectionInput(account_id=connection.account_id, username=connection.username, password=password, program_serial=connection.program_serial)
    except Exception as error:
        raise HTTPException(400, "Enter a password for a new account.") from error
    save_connection(validated);return {"ok":True,"profile":validated.program_serial,"connection":{"account_id":validated.account_id,"username":validated.username}}
@app.delete("/api/setup")
def clear_setup(profile:str):clear_connection(profile);return {"ok":True}
@app.post("/api/setup/test")
def test_setup(connection:ConnectionInput|None=None,profile:str="demo"):
    candidate=connection or stored_connection(profile)
    if candidate is None:raise HTTPException(400,"No saved connection for this profile.")
    try:token(candidate)
    except FortiFlexError as error:raise HTTPException(502,str(error)) from error
    return {"ok":True,"message":"Credentials validated."}
@app.post("/api/inventory/populate")
def populate_inventory(profile:str):
    if is_sample_profile(profile):raise HTTPException(400,"Demo inventory is already populated")
    account=stored_connection(profile)
    if not account:raise HTTPException(400,"No saved account for this profile")
    try:inventory=[item for item in list_entitlements(account, lambda endpoint, request, response: record_api_sample(profile, "Entitlement inventory", endpoint, request, response)) if item.get("serialNumber")]
    except FortiFlexError as error:raise HTTPException(502,str(error)) from error
    added,kept=0,0
    with connect(profile) as c:
        for item in inventory:
            serial,name=item["serialNumber"],item.get("description") or item["serialNumber"]
            if c.execute("SELECT 1 FROM devices WHERE serial=?",(serial,)).fetchone():
                kept+=1;c.execute("UPDATE devices SET portal_name=?,friendly_name=?,entitlement_status=?,config_id=?,entitlement_start_date=?,entitlement_end_date=? WHERE serial=?",(name,name,item.get("status"),item.get("configId"),item.get("startDate"),item.get("endDate"),serial))
            else:
                added+=1;c.execute("INSERT INTO devices(serial,friendly_name,department_code,notes,product,portal_name,entitlement_status,config_id,entitlement_start_date,entitlement_end_date) VALUES(?,?,?,?,?,?,?,?,?,?)",(serial,name,"UNASSIGNED","","FortiFlex entitlement",name,item.get("status"),item.get("configId"),item.get("startDate"),item.get("endDate")))
        c.execute("UPDATE refresh_state SET status='ready',message=?,refreshed_at=? WHERE id=1",(f"Inventory populated: {added} new, {kept} retained",datetime.now(timezone.utc).isoformat()))
    return {"ok":True,"inserted":added,"existing":kept}
@app.post("/api/configurations/populate")
def populate_configurations(profile: str):
    if is_sample_profile(profile): raise HTTPException(400,"Demo profile has no FortiFlex configuration catalogue")
    account = stored_connection(profile)
    if not account: raise HTTPException(400,"No saved account for this profile")
    try:
        entries = list_configurations(account, lambda endpoint, request, response: record_api_sample(profile, "Configuration catalogue", endpoint, request, response))
    except FortiFlexError as error:
        raise HTTPException(502,str(error)) from error
    now = datetime.now(timezone.utc).isoformat()
    with connect(profile) as c:
        for entry in entries:
            c.execute("INSERT INTO configurations(config_id,product,config_name,features,status,notes,refreshed_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(config_id) DO UPDATE SET product=excluded.product,config_name=excluded.config_name,features=excluded.features,status=excluded.status,refreshed_at=excluded.refreshed_at",(entry["config_id"],entry["product"],entry["config_name"],json.dumps(entry["features"],sort_keys=True),entry["status"],"",now))
    return {"ok":True,"configurations_seen":len(entries)}

@app.post("/api/catalog/populate")
def populate_catalog(profile: str):
    """Refresh the two linked FortiFlex catalogues in one explicit action."""
    inventory = populate_inventory(profile)
    configurations = populate_configurations(profile)
    return {"ok": True, "inventory": inventory, "configurations": configurations}

def pull_worker(profile:str,selected:list[str]):
    job,account=PULL_JOBS[profile],stored_connection(profile)
    try:
        if account is None: raise RuntimeError("No saved account for this profile")
        access_token=token(account)
        for day in selected:
            try:
                readings=daily_points(account,day,access_token, lambda endpoint, request, response: record_api_sample(profile, "Daily point usage", endpoint, request, response))
                with connect(profile) as c:
                    known={r["serial"] for r in c.execute("SELECT serial FROM devices")};now=datetime.now(timezone.utc).isoformat()
                    for item in readings:
                        if item["serial"] in known and item["points"] is not None:c.execute("INSERT INTO usage_records(serial,usage_date,points,source,refreshed_at) VALUES(?,?,?,?,?) ON CONFLICT(serial,usage_date) DO UPDATE SET points=excluded.points,source=excluded.source,refreshed_at=excluded.refreshed_at",(item["serial"],day,float(item["points"]),"fortiflex",now))
                    c.execute("INSERT INTO usage_day_coverage(account_id,usage_date,status,detail,refreshed_at) VALUES(?,?,?,?,?) ON CONFLICT(account_id,usage_date) DO UPDATE SET status='complete',detail='',refreshed_at=excluded.refreshed_at",(account.account_id,day,"complete","",now))
            except Exception as error:
                with connect(profile) as c:c.execute("INSERT INTO usage_day_coverage(account_id,usage_date,status,detail,refreshed_at) VALUES(?,?,?,?,?) ON CONFLICT(account_id,usage_date) DO UPDATE SET status='failed',detail=excluded.detail,refreshed_at=excluded.refreshed_at",(account.account_id,day,"failed",str(error)[:180],datetime.now(timezone.utc).isoformat()))
            job["completed"]+=1;job["message"]="Retrieved %s of %s day readings"%(job["completed"],job["total"]);time.sleep(1)
        job.update({"status":"complete","message":"Cached %s complete day(s); today was excluded."%len(selected)})
    except Exception as error:job.update({"status":"failed","message":"Pull stopped: "+str(error)[:180]})
    finally:PULL_LOCK.release()
@app.post("/api/pull/{mode}")
def pull(mode:str,profile:str):
    if is_sample_profile(profile):raise HTTPException(400,"Sample data is already local")
    account=stored_connection(profile)
    if not account:raise HTTPException(400,"No saved account for this profile")
    if not PULL_LOCK.acquire(False):raise HTTPException(409,"Another pull is already running")
    try:
        if mode=="missing":selected=[x["usage_date"] for x in coverage(profile,days_back(7)) if not x["complete"]]
        elif mode=="full":selected=days_back(90)
        else:raise HTTPException(404,"Unknown pull mode")
        if not selected:PULL_LOCK.release();return {"ok":True,"message":"No completed days need a pull."}
        PULL_JOBS[profile]={"status":"running","completed":0,"total":len(selected),"message":"Starting secure daily pull"}
        threading.Thread(target=pull_worker,args=(profile,selected),daemon=True).start()
        return {"ok":True,"message":"Started %s pull for %s completed day(s)."%(mode,len(selected))}
    except Exception:
        if PULL_LOCK.locked():PULL_LOCK.release()
        raise
@app.get("/api/export/devices.csv")
def export_devices(profile:str="demo"):
    output=io.StringIO();writer=csv.writer(output);fields=["serial","portal_name","department_code","entitlement_status","config_id","notes"];writer.writerow(fields)
    for row in devices(profile):writer.writerow([row.get(x,"") for x in fields])
    return Response(output.getvalue(),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=devices.csv"})
@app.get("/api/export/summary.json")
def export_summary(profile: str="demo", department: str="", view: str="30"):
    days = view_days(view)
    rollup = department_rollup(profile, days, department)
    marks = coverage(profile, days)
    total = round(sum(row["points"] for row in rollup), 2)
    payload = {
        "schema_version": 1,
        "profile": profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"view": view, "start_date": days[0], "end_date": days[-1], "department_filter": department or None},
        "total_points": total,
        "missing_readings": sum(1 for mark in marks if not mark["complete"]),
        "department_points": rollup,
    }
    suffix = department or "all-departments"
    return Response(json.dumps(payload, indent=2), media_type="application/json", headers={"Content-Disposition":f'attachment; filename="fortiflex-{view}-{suffix}-summary.json"'})
@app.get("/")
@app.get("/index.html", include_in_schema=False)
def home():
    return FileResponse(Path(__file__).with_name("templates") / "index.html")
