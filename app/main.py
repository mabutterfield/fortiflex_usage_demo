from __future__ import annotations
import calendar, csv, io, json, os, threading, time
from datetime import date, datetime, timedelta, timezone
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .config import ConnectionInput, clear_connection, connection_summary, list_profiles, save_connection, stored_connection, stored_connections
from .db import connect
from .fortiflex import FortiFlexError, daily_points, list_configurations, list_entitlements, token

app = FastAPI(title="FortiFlex departmental chargeback demo")
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
    accounts = stored_connections(profile)
    if profile == "demo": return [{"usage_date":d,"complete":True} for d in days]
    if not days: return []
    with connect(profile) as c:
        rows = c.execute("SELECT usage_date,COUNT(*) count FROM usage_day_coverage WHERE status='complete' AND usage_date IN (%s) GROUP BY usage_date" % ",".join("?"*len(days)),days).fetchall()
    found, expected = {r["usage_date"]:r["count"] for r in rows},len(accounts)
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

@app.get("/api/profiles")
def profiles(): return list_profiles()
@app.get("/api/status")
def status(profile: str="demo"):
    with connect(profile) as c: row=c.execute("SELECT status,message,refreshed_at FROM refresh_state WHERE id=1").fetchone()
    return {"profile":profile,"sample_mode":profile=="demo","connection":connection_summary(profile),"refresh":dict(row),"pull":PULL_JOBS.get(profile)}
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
@app.put("/api/departments/{code}")
def save_department(code:str,edit:DepartmentEdit,profile:str="demo"):
    if code!=edit.code or not code.strip():raise HTTPException(400,"Department code is required and cannot be renamed")
    with connect(profile) as c:c.execute("INSERT INTO departments(code,display_name,notes) VALUES(?,?,?) ON CONFLICT(code) DO UPDATE SET display_name=excluded.display_name,notes=excluded.notes",(code,edit.display_name.strip() or code,edit.notes))
    return {"ok":True}
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
        for saved in stored_connections(connection.program_serial):
            if saved.account_id == connection.account_id and saved.username == connection.username:
                password = saved.password
                break
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
    if profile=="demo":raise HTTPException(400,"Demo inventory is already populated")
    accounts=stored_connections(profile)
    if not accounts:raise HTTPException(400,"No saved account for this profile")
    try:inventory=[item for account in accounts for item in list_entitlements(account) if item.get("serialNumber")]
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
    if profile == "demo": raise HTTPException(400,"Demo profile has no FortiFlex configuration catalogue")
    accounts = stored_connections(profile)
    if not accounts: raise HTTPException(400,"No saved account for this profile")
    try:
        entries = [entry for account in accounts for entry in list_configurations(account)]
    except FortiFlexError as error:
        raise HTTPException(502,str(error)) from error
    now = datetime.now(timezone.utc).isoformat()
    with connect(profile) as c:
        for entry in entries:
            c.execute("INSERT INTO configurations(config_id,product,config_name,features,status,notes,refreshed_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(config_id) DO UPDATE SET product=excluded.product,config_name=excluded.config_name,features=excluded.features,status=excluded.status,refreshed_at=excluded.refreshed_at",(entry["config_id"],entry["product"],entry["config_name"],json.dumps(entry["features"],sort_keys=True),entry["status"],"",now))
    return {"ok":True,"configurations_seen":len(entries)}

def pull_worker(profile:str,selected:list[str]):
    job,accounts=PULL_JOBS[profile],stored_connections(profile)
    try:
        tokens={a.account_id:token(a) for a in accounts}
        for day in selected:
            for account in accounts:
                try:
                    readings=daily_points(account,day,tokens[account.account_id])
                    with connect(profile) as c:
                        known={r["serial"] for r in c.execute("SELECT serial FROM devices")};now=datetime.now(timezone.utc).isoformat()
                        for item in readings:
                            if item["serial"] in known and item["points"] is not None:c.execute("INSERT INTO usage_records(serial,usage_date,points,source,refreshed_at) VALUES(?,?,?,?,?) ON CONFLICT(serial,usage_date) DO UPDATE SET points=excluded.points,source=excluded.source,refreshed_at=excluded.refreshed_at",(item["serial"],day,float(item["points"]),"fortiflex",now))
                        c.execute("INSERT INTO usage_day_coverage(account_id,usage_date,status,detail,refreshed_at) VALUES(?,?,?,?,?) ON CONFLICT(account_id,usage_date) DO UPDATE SET status='complete',detail='',refreshed_at=excluded.refreshed_at",(account.account_id,day,"complete","",now))
                except Exception as error:
                    with connect(profile) as c:c.execute("INSERT INTO usage_day_coverage(account_id,usage_date,status,detail,refreshed_at) VALUES(?,?,?,?,?) ON CONFLICT(account_id,usage_date) DO UPDATE SET status='failed',detail=excluded.detail,refreshed_at=excluded.refreshed_at",(account.account_id,day,"failed",str(error)[:180],datetime.now(timezone.utc).isoformat()))
                job["completed"]+=1;job["message"]="Retrieved %s of %s account-day readings"%(job["completed"],job["total"]);time.sleep(1)
        job.update({"status":"complete","message":"Cached %s complete day(s); today was excluded."%len(selected)})
    except Exception as error:job.update({"status":"failed","message":"Pull stopped: "+str(error)[:180]})
    finally:PULL_LOCK.release()
@app.post("/api/pull/{mode}")
def pull(mode:str,profile:str):
    if profile=="demo":raise HTTPException(400,"Sample data is already local")
    accounts=stored_connections(profile)
    if not accounts:raise HTTPException(400,"No saved account for this profile")
    if not PULL_LOCK.acquire(False):raise HTTPException(409,"Another pull is already running")
    try:
        if mode=="missing":selected=[x["usage_date"] for x in coverage(profile,list(reversed(days_back(90)))) if not x["complete"]][:7]
        elif mode=="full":selected=days_back(90)
        else:raise HTTPException(404,"Unknown pull mode")
        if not selected:PULL_LOCK.release();return {"ok":True,"message":"No completed days need a pull."}
        PULL_JOBS[profile]={"status":"running","completed":0,"total":len(selected)*len(accounts),"message":"Starting secure daily pull"}
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
@app.get("/",response_class=HTMLResponse)
def home():return HTMLResponse(HTML)

HTML = """<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><title>FortiFlex usage</title><style>
*{box-sizing:border-box}body{margin:0;font:14px system-ui;background:#f3f6fa;color:#17233a}header{background:#1268b3;color:#fff;padding:15px 4vw}h1{font-size:21px;margin:0}main{max-width:1350px;margin:20px auto;padding:0 18px}.bar,.card{background:#fff;border-radius:8px;padding:15px;margin-bottom:15px;box-shadow:0 1px 5px #1234}.bar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}label{display:grid;gap:4px;font-size:12px;font-weight:700}input,select,button{padding:8px;border:1px solid #b9c7d6;border-radius:5px;background:#fff}button{background:#1769aa;color:#fff;border:0;font-weight:700;cursor:pointer}.secondary{background:#60798e}.metric{border-left:4px solid #37a3dd;padding:13px;background:#fff;border-radius:5px}.metric b{display:block;font-size:23px;margin-top:6px}.divider{border:0;border-top:3px solid #ccd8e3;margin:25px 0}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #e2e8f0;text-align:left}th{font-size:11px;color:#49657d}.scroll{overflow:auto}.calendar{display:grid;grid-template-columns:repeat(7,38px);gap:5px}.day{height:34px;border-radius:4px;text-align:center;padding-top:8px;font-size:11px;font-weight:700}.good{background:#ccebd5;color:#155f30}.bad{background:#ffd5d5;color:#9c2020}.outside{background:#e8edf2;color:#728196}.unavailable{background:#f7f8fa;color:#adb7c2}.muted{font-size:12px;color:#587085}canvas{width:100%;height:260px;background:#fafcff;border-radius:5px;cursor:crosshair}dialog{border:0;border-radius:9px;box-shadow:0 12px 50px #0006;width:min(520px,95vw)}dialog label{margin:10px 0}dialog menu{padding:0;display:flex;gap:8px;justify-content:end}.serial{background:none;color:#1769aa;padding:0;text-decoration:underline}.hide{display:none}#tip{position:fixed;display:none;background:#17233a;color:#fff;padding:7px 9px;border-radius:5px;font-size:12px;pointer-events:none;z-index:5}</style></head><body><header><h1>FortiFlex departmental usage</h1></header><main>
<section class=bar><label>Profile<select id=profile></select></label><button id=populate>(Re) Populate inventory</button><button id=populateConfigs>(Re) Populate configurations</button><button class=secondary onclick=openConnection()>Edit connection</button><button onclick=testConnection()>Test connection</button><button id=pullMissing>Pull week</button><button id=pullFull class=secondary>Pull full data (90 days)</button><button class=secondary onclick=openCalendar()>Reading calendar</button><span class=muted id=pullStatus></span></section>
<section class=bar><label>Department<select id=department></select></label><label>Display range<select id=view><option value=7>Last 7 complete days</option><option value=30 selected>Last 30 complete days</option><option value=90>Last 90 complete days</option><option value=last_month>Last Month</option></select></label><div class=metric>Points used<b id=rangePoints>—</b><span class=muted id=rangeCaption></span></div><div class='metric hide' id=missingMetric>Missed readings<b id=gapCount>—</b><span class=muted>cache gaps in this window</span></div><span class=muted>Changing department or display range redraws only from the local cache.</span></section>
<section class=card><h2 id=usageTitle>Daily point usage</h2><p class=muted>Last 30 complete days; today is excluded.</p><canvas id=departmentChart width=1200 height=260></canvas></section>
<hr class=divider>
<section class=card><h2>Device inventory</h2><div class=bar><label>Department<select id=filterDepartment></select></label><label>Status<select id=filterStatus multiple size=2><option value=ACTIVE selected>ACTIVE</option><option value=PENDING selected>PENDING</option><option value=STOPPED>STOPPED</option><option value=EXPIRED>EXPIRED</option></select></label><label>Product<select id=filterProduct></select></label><label>Config ID<input id=filterConfig placeholder=Any></label><button onclick=loadInventory()>Filter local cache</button></div><p class=muted>Use Command/Ctrl-click to select more statuses.</p><div class=scroll><table id=inventory></table></div></section><section class=card><h2 id=deviceTitle>Daily device usage</h2><p class=muted>Click a serial number above to chart its local daily history.</p><canvas id=deviceChart width=1200 height=260></canvas></section><section class=card><h2>Configuration inventory</h2><p class=muted>FortiFlex configuration metadata; only Notes is editable locally.</p><div class=bar><label>Product<select id=configProduct></select></label><label>Status<select id=configStatus><option value=''>All statuses</option><option value=ACTIVE selected>ACTIVE</option><option value=DISABLED>DISABLED</option></select></label><button onclick=loadConfigurations()>Filter local cache</button></div><div class=scroll><table id=configInventory></table></div></section><section class=card><h2>Department inventory</h2><p class=muted>Local chargeback metadata only.</p><div class=scroll><table id=departmentInventory></table></div></section>
</main><div id=tip></div><dialog id=connection><form method=dialog><h2>Edit connection</h2><p class=muted id=connectionStatus></p><label>Account ID<input id=account type=number min=1></label><label>API username<input id=username></label><label>API password<input id=password type=password></label><label>Program serial<input id=program></label><p id=connectionMessage></p><menu><button value=cancel class=secondary>Close</button><button type=button onclick=saveConnection()>Save connection</button></menu></form></dialog><dialog id=calendarDialog><form method=dialog><h2>Reading calendar</h2><div class=bar><button type=button class=secondary onclick=moveCalendar(-1)>‹ Previous</button><label>Month<input id=calendarMonth type=month onchange=loadCalendar()></label><button type=button class=secondary onclick=moveCalendar(1)>Next ›</button></div><p class=muted>Green: cached. Red: can be retrieved. Grey: outside FortiFlex's 90-day retrieval window. Light grey: before the entitlement start date or future.</p><div id=calendar class=calendar></div><menu><button value=cancel>Close</button></menu></form></dialog><dialog id=editor><form method=dialog><h2 id=editTitle></h2><label>Portal name (read-only)<input id=name readonly></label><label>Department<select id=editDepartment></select></label><label>Notes<input id=notes></label><menu><button value=cancel class=secondary>Cancel</button><button type=button onclick=saveDevice()>Save</button></menu></form></dialog>
<script>
const $=x=>document.getElementById(x),esc=x=>String(x??'—').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');let active=new URLSearchParams(location.search).get('profile')||'demo',editing,selectedDevice='';const profile=()=>active,api=(p,o)=>fetch(p+(p.includes('?')?'&':'?')+'profile='+encodeURIComponent(profile()),o).then(async r=>{let d=await r.json();if(!r.ok)throw Error(d.detail||'Request failed');return d}),option=x=>'<option value="'+esc(x.code||x.id)+'">'+esc(x.code?x.code+' — '+x.display_name:x.label)+'</option>';
async function boot(){let p=await fetch('/api/profiles').then(x=>x.json());$('profile').innerHTML=p.map(option).join('');$('profile').value=active;$('profile').onchange=e=>location.search='?profile='+encodeURIComponent(e.target.value);$('populate').onclick=populate;$('populateConfigs').onclick=populateConfigs;$('pullMissing').onclick=()=>pull('missing');$('pullFull').onclick=()=>pull('full');$('department').onchange=loadDashboard;$('view').onchange=loadDashboard;await loadDepartments();await loadDashboard();await loadInventory();await loadConfigurations();setInterval(loadStatus,3000)}
async function loadStatus(){let s=await api('/api/status'),p=s.pull;$('pullStatus').textContent=p?p.message+(p.status==='running'?' ('+p.completed+'/'+p.total+')':''):s.refresh.message;['populate','populateConfigs','pullMissing','pullFull'].forEach(x=>$(x).classList.toggle('hide',s.sample_mode))}
async function loadDepartments(){let d=await api('/api/departments'),o='<option value="">All departments</option>'+d.map(option).join('');$('department').innerHTML=o;$('filterDepartment').innerHTML=o;$('departmentInventory').innerHTML='<tr><th>Code</th><th>Name</th><th>Entitlements</th><th>Notes</th><th></th></tr>'+d.map(x=>'<tr><td>'+esc(x.code)+'</td><td><input id="dn_'+esc(x.code)+'" value="'+esc(x.display_name)+'"></td><td>'+x.entitlement_count+'</td><td><input id="dt_'+esc(x.code)+'" value="'+esc(x.notes)+'"></td><td><button onclick="saveDepartment(\\''+esc(x.code)+'\\')">Save</button></td></tr>').join('')}
async function saveDepartment(c){await api('/api/departments/'+encodeURIComponent(c),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:c,display_name:$('dn_'+c).value,notes:$('dt_'+c).value})});loadDepartments()}
async function loadDashboard(){let dep=$('department').value,v=$('view').value,d=await api('/api/dashboard?department='+encodeURIComponent(dep)+'&view='+v);$('rangePoints').textContent=d.points.toFixed(2);$('rangeCaption').textContent=$('view').selectedOptions[0].text;$('gapCount').textContent=d.missing_readings;$('missingMetric').classList.toggle('hide',d.missing_readings===0);$('usageTitle').textContent='Daily point usage — '+(dep||'All departments');draw('departmentChart',d.series,'bar');if(selectedDevice)loadDevice(selectedDevice,false)}
function draw(id,d,kind){let c=$(id),x=c.getContext('2d'),w=c.width,h=c.height,left=52,bottom=35,a=d.map(r=>r.points).filter(v=>v!=null),m=Math.max(...a,1);c._usage=d;c._kind=kind;x.clearRect(0,0,w,h);x.strokeStyle='#d8e4ee';x.fillStyle='#49657d';x.font='11px system-ui';for(let i=0;i<4;i++){let y=20+i*(h-55)/3;x.beginPath();x.moveTo(left,y);x.lineTo(w-10,y);x.stroke();x.fillText((m*(3-i)/3).toFixed(1),5,y+4)}let step=d.length<=8?1:d.length<=31?7:14;for(let i=0;i<d.length;i+=step){let px=left+i*(w-left-15)/Math.max(d.length-1,1);x.fillText(d[i].usage_date.slice(5),px-13,h-12)}if(kind==='bar'){x.fillStyle='#8fb3df';d.forEach((r,i)=>{if(r.points==null)return;let px=left+i*(w-left-15)/d.length,bar=(w-left-15)/d.length*.72,py=h-bottom-r.points/m*(h-55);x.fillRect(px,py,bar,h-bottom-py)});return}x.strokeStyle='#1769aa';x.lineWidth=3;x.beginPath();let prev=false;d.forEach((r,i)=>{let px=left+i*(w-left-15)/Math.max(d.length-1,1);if(r.points==null){prev=false;return}let py=h-bottom-r.points/m*(h-55);prev?x.lineTo(px,py):x.moveTo(px,py);prev=true});x.stroke()}
function chartHover(event){let c=event.currentTarget,d=c._usage||[];if(!d.length)return;let r=c.getBoundingClientRect(),px=(event.clientX-r.left)*c.width/r.width,left=52,index=Math.max(0,Math.min(d.length-1,Math.round((px-left)/(c.width-left-15)*(d.length-1)))),point=d[index],tip=$('tip');tip.textContent=point.usage_date+' — '+(point.points==null?'no cached reading':point.points.toFixed(2)+' points');tip.style.left=(event.clientX+12)+'px';tip.style.top=(event.clientY+12)+'px';tip.style.display='block'}['departmentChart','deviceChart'].forEach(id=>{$(id).onmousemove=chartHover;$(id).onmouseleave=()=>{$('tip').style.display='none'}})
async function loadInventory(){let allConfigs=await api('/api/configurations'),oldProduct=$('filterProduct').value,products=[...new Set(allConfigs.map(x=>x.product).filter(Boolean))].sort();$('filterProduct').innerHTML='<option value="">All products</option>'+products.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join('');$('filterProduct').value=products.includes(oldProduct)?oldProduct:'';let states=[...$('filterStatus').selectedOptions].map(x=>x.value).join(','),q='?department='+encodeURIComponent($('filterDepartment').value)+'&status='+encodeURIComponent(states)+'&product='+encodeURIComponent($('filterProduct').value)+'&config_id='+encodeURIComponent($('filterConfig').value),d=await api('/api/devices'+q);$('inventory').innerHTML='<tr><th>Serial</th><th>Portal name</th><th>Department</th><th>Status</th><th>Config ID</th><th>Configuration name</th><th>Product</th><th>Notes</th><th></th></tr>'+d.map(x=>'<tr><td><button class=serial onclick="selectDevice(\\''+esc(x.serial)+'\\')">'+esc(x.serial)+'</button></td><td>'+esc(x.portal_name||x.friendly_name)+'</td><td>'+esc(x.department_code)+'</td><td>'+esc(x.entitlement_status)+'</td><td><button class=serial onclick="showConfig('+x.config_id+')">'+esc(x.config_id)+'</button></td><td>'+esc(x.config_name||'—')+'</td><td>'+esc(x.config_product||'—')+'</td><td>'+esc(x.notes||'')+'</td><td><button onclick="editDevice(\\''+esc(x.serial)+'\\')">Edit</button></td></tr>').join('');window.inventory=d}
function selectDevice(s){selectedDevice=s;loadDevice(s,true)}async function loadDevice(s,shouldScroll){if(!s){$('deviceTitle').textContent='Daily device usage';return draw('deviceChart',[],'bar')}let d=await api('/api/devices/'+encodeURIComponent(s)+'/usage?view='+$('view').value);$('deviceTitle').textContent='Daily device usage — '+s;draw('deviceChart',d,'bar');if(shouldScroll)$('deviceChart').scrollIntoView({behavior:'smooth',block:'center'})}
async function populate(){if(!confirm('Download current entitlement inventory? Existing department assignments and notes are retained.'))return;let d=await api('/api/inventory/populate',{method:'POST'});alert('Inventory updated: '+d.inserted+' new, '+d.existing+' existing.');loadDepartments();loadInventory()}async function pull(m){let d=await api('/api/pull/'+m,{method:'POST'});alert(d.message)}
async function populateConfigs(){if(!confirm('Download the FortiFlex configuration catalogue? Existing local configuration notes are retained.'))return;try{let d=await api('/api/configurations/populate',{method:'POST'});alert('Configuration catalogue updated: '+d.configurations_seen+' configuration(s).');loadConfigurations();loadInventory()}catch(e){alert('Configuration pull failed: '+e.message)}}function profileSummary(raw,product){try{let f=JSON.parse(raw),params=f.parameters||[],values=n=>params.filter(x=>x.name===n&&x.value&&x.value!=='NONE').map(x=>String(x.value)),get=n=>values(n)[0],parts=[];if(get('Number of CPUs'))parts.push(get('Number of CPUs')+' vCPU');if(get('Daily Storage (GB)'))parts.push(get('Daily Storage (GB)')+' GB/day');if(get('Device Model'))parts.push(get('Device Model'));let packageName={FC:'FortiCare only',ATP:'ATP',ENT:'Enterprise',UTP:'UTP',FWBSTD:'Standard',FWBADV:'Advanced'}[get('Service Package')]||get('Service Package');if(packageName)parts.push(packageName);let support=values('Support Services').length,addons=values('Addons').length;if(support||addons)parts.push((support?'Support':'')+(support&&addons?' + ':'')+(addons?addons+' add-on'+(addons===1?'':'s'):''));return parts.join(' · ')||'—'}catch(e){return '—'}}async function loadConfigurations(){let all=await api('/api/configurations'),old=$('configProduct').value,products=[...new Set(all.map(x=>x.product).filter(Boolean))].sort();$('configProduct').innerHTML='<option value="">All products</option>'+products.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join('');$('configProduct').value=products.includes(old)?old:'';let d=all.filter(x=>(!$('configProduct').value||x.product===$('configProduct').value)&&(!$('configStatus').value||x.status===$('configStatus').value));$('configInventory').innerHTML='<tr><th>Config ID</th><th>Name</th><th>Product</th><th>Profile</th><th>Status</th><th>Notes</th><th></th></tr>'+d.map(x=>'<tr id="config_'+x.config_id+'"><td>'+x.config_id+'</td><td>'+esc(x.config_name||'—')+'</td><td>'+esc(x.product)+'</td><td>'+esc(profileSummary(x.features,x.product))+'</td><td>'+esc(x.status||'—')+'</td><td><input id="cn_'+x.config_id+'" value="'+esc(x.notes||'')+'"></td><td><button onclick="saveConfiguration('+x.config_id+')">Save</button></td></tr>').join('')}async function saveConfiguration(id){await api('/api/configurations/'+id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({notes:$('cn_'+id).value})});loadConfigurations()}async function showConfig(id){$('configProduct').value='';$('configStatus').value='';await loadConfigurations();let row=$('config_'+id);if(row)row.scrollIntoView({behavior:'smooth',block:'center'})}
async function openConnection(){let s=await api('/api/status'),a=s.connection.accounts&&s.connection.accounts[0];$('connectionStatus').textContent=a?'Saved account '+a.account_id+' / '+a.username+'; password: ******** (leave blank to retain it).':'No saved connection for this profile.';$('program').value=profile()==='demo'?'':profile();$('account').value=a?a.account_id:'';$('username').value=a?a.username:'';$('password').value='';$('password').placeholder=a?'******** (saved)':'Required for a new account';$('connectionMessage').textContent='';$('connection').showModal()}async function testConnection(){try{let d=await api('/api/setup/test',{method:'POST'});alert('Connection confirmed: '+d.message)}catch(e){alert('Connection test failed: '+e.message)}}async function saveConnection(){try{let d=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({account_id:+$('account').value,username:$('username').value,password:$('password').value,program_serial:$('program').value})}).then(async r=>{let d=await r.json();if(!r.ok)throw Error(d.detail);return d});location.search='?profile='+encodeURIComponent(d.profile)}catch(e){$('connectionMessage').textContent=e.message}}
function monthValue(d){return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')}async function openCalendar(){if(!$('calendarMonth').value)$('calendarMonth').value=monthValue(new Date());$('calendarDialog').showModal();loadCalendar()}function moveCalendar(delta){let d=new Date($('calendarMonth').value+'-01T12:00:00');d.setMonth(d.getMonth()+delta);$('calendarMonth').value=monthValue(d);loadCalendar()}async function loadCalendar(){let m=$('calendarMonth').value;if(!m)return;let d=await api('/api/coverage?month='+m),weekday=['Su','Mo','Tu','We','Th','Fr','Sa'],start=new Date(m+'-01T12:00:00').getDay(),html=weekday.map(x=>'<b class=muted>'+x+'</b>').join('');for(let i=0;i<start;i++)html+='<span></span>';$('calendar').innerHTML=html+d.days.map(x=>'<span title="'+x.usage_date+' — '+x.state+'" class="day '+({complete:'good',missing:'bad',outside_retention:'outside',before_start:'unavailable',future:'unavailable'}[x.state])+'">'+x.usage_date.slice(8)+'</span>').join('')}
async function editDevice(s){let x=window.inventory.find(v=>v.serial===s);editing=x;$('editTitle').textContent='Edit entitlement — '+s;$('name').value=x.portal_name||x.friendly_name;$('notes').value=x.notes||'';let d=await api('/api/departments');$('editDepartment').innerHTML=d.map(option).join('');$('editDepartment').value=x.department_code;$('editor').showModal()}async function saveDevice(){await api('/api/devices/'+encodeURIComponent(editing.serial),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({department_code:$('editDepartment').value,notes:$('notes').value})});$('editor').close();loadDepartments();loadDashboard();loadInventory()}boot();
</script></body></html>"""
