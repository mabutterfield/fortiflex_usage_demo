(() => {
  const themes = [
    ["mariner", "Mariner"],
    ["retro", "Retro"],
    ["dark-matter", "Dark Matter"],
    ["onyx", "Onyx"],
    ["eclipse", "Eclipse"],
  ];
  const css = `
    [data-theme=mariner]{--page:#eef2f5;--surface:#fff;--text:#17233a;--muted:#587085;--header:#1268b3;--button:#1769aa;--button-alt:#60798e;--border:#ccd8e3;--grid:#d8e4ee;--link:#1769aa;--metric:#37a3dd;--canvas:#fafcff;--tip:#17233a;--alert:#b42318;--alert-bg:#fff0ef;--alert-text:#8f1d14}
    [data-theme=dark-matter]{--page:#202020;--surface:#272727;--text:#d2d2d2;--muted:#999;--header:#454545;--button:#6865aa;--button-alt:#444;--border:#3a3a3a;--grid:#3a3a3a;--link:#918cd1;--metric:#6b68ad;--canvas:#252525;--tip:#141414;--shadow:#00000044;--good-bg:#403d68;--good-text:#e1ddff;--bad-bg:#60343d;--bad-text:#ffd9dc;--outside:#3a3a3a;--unavailable:#303030;--alert:#ff6b73;--alert-bg:#5c2930;--alert-text:#ffe1e3}
    [data-theme=onyx]{--page:#202020;--surface:#272727;--text:#d2d2d2;--muted:#999;--header:#454545;--button:#46955c;--button-alt:#444;--border:#3a3a3a;--grid:#3a3a3a;--link:#58b674;--metric:#46955c;--canvas:#252525;--tip:#141414;--shadow:#00000044;--good-bg:#245234;--good-text:#d3f0da;--bad-bg:#60343d;--bad-text:#ffd9dc;--outside:#3a3a3a;--unavailable:#303030;--alert:#ff6b73;--alert-bg:#5c2930;--alert-text:#ffe1e3}
    [data-theme=eclipse]{--page:#202020;--surface:#272727;--text:#d2d2d2;--muted:#999;--header:#454545;--button:#ec9300;--button-alt:#444;--border:#3a3a3a;--grid:#3a3a3a;--link:#ffae2d;--metric:#ec9300;--canvas:#252525;--tip:#141414;--shadow:#00000044;--good-bg:#554526;--good-text:#ffebc3;--bad-bg:#60343d;--bad-text:#ffd9dc;--outside:#3a3a3a;--unavailable:#303030;--alert:#ff6b73;--alert-bg:#5c2930;--alert-text:#ffe1e3}
    [data-theme=retro]{--page:#d5e4e5;--surface:#e5f0f1;--text:#294e4c;--muted:#6c8888;--header:#bdd2d3;--button:#168983;--button-alt:#6c9090;--border:#bad0d0;--grid:#c5d9d9;--link:#087b76;--metric:#168983;--canvas:#e9f3f4;--tip:#1d5552;--shadow:#79999a55;--good-bg:#c5e6db;--good-text:#155f50;--bad-bg:#f1d2d2;--bad-text:#892b2b;--outside:#cadada;--unavailable:#e1ebeb;--alert:#b42318;--alert-bg:#fbe2e2;--alert-text:#892b2b}
    #apiTray{position:fixed;z-index:10;top:0;right:0;width:min(620px,96vw);height:100vh;padding:0 20px 20px;background:var(--surface);color:var(--text);box-shadow:-8px 0 25px var(--shadow);overflow:auto;transform:translateX(105%);transition:transform .2s ease}#apiTray.open{transform:translateX(0)}#apiTray header{position:sticky;top:0;z-index:1;background:var(--surface);color:var(--text);padding:20px 0 14px;min-height:0;border-bottom:1px solid var(--border)}.tray-head{display:flex;justify-content:space-between;align-items:center;gap:15px}.api-sample{margin:15px 0;padding:12px;border:1px solid var(--border);border-radius:4px}.api-sample summary{cursor:pointer;font-weight:800}.api-sample pre{margin:12px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;font:12px ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--text)}
    .day.delete-day.good{background:var(--good-bg);color:var(--good-text)}.day.delete-day.bad{background:var(--bad-bg);color:var(--bad-text)}.day.delete-day.outside{background:var(--outside);color:var(--muted)}.day.delete-day.unavailable{background:var(--unavailable);color:var(--muted)}
  `;
  const picker = document.getElementById("theme");

  if (!picker) return;
  document.head.append(Object.assign(document.createElement("style"), { textContent: css }));
  picker.innerHTML = themes
    .map(([id, label]) => `<option value="${id}">${label}</option>`)
    .join("");

  const color = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  draw = (id, data, kind) => {
    const canvas = document.getElementById(id);
    const context = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    const left = 52;
    const bottom = 35;
    const points = data.map((row) => row.points).filter((value) => value != null);
    const maximum = Math.max(...points, 1);

    canvas._usage = data;
    canvas._kind = kind;
    context.clearRect(0, 0, width, height);
    context.strokeStyle = color("--grid");
    context.fillStyle = color("--muted");
    context.font = "11px system-ui";
    for (let index = 0; index < 4; index += 1) {
      const y = 20 + (index * (height - 55)) / 3;
      context.beginPath();
      context.moveTo(left, y);
      context.lineTo(width - 10, y);
      context.stroke();
      context.fillText((maximum * (3 - index) / 3).toFixed(1), 5, y + 4);
    }
    const step = data.length <= 8 ? 1 : data.length <= 31 ? 7 : 14;
    for (let index = 0; index < data.length; index += step) {
      const x = left + (index * (width - left - 15)) / Math.max(data.length - 1, 1);
      context.fillText(data[index].usage_date.slice(5), x - 13, height - 12);
    }
    if (kind === "bar") {
      context.fillStyle = color("--button");
      data.forEach((row, index) => {
        if (row.points == null) return;
        const x = left + (index * (width - left - 15)) / data.length;
        const barWidth = ((width - left - 15) / data.length) * 0.72;
        const y = height - bottom - (row.points / maximum) * (height - 55);
        context.fillRect(x, y, barWidth, height - bottom - y);
      });
    }
  };

  const saved = localStorage.getItem("fortiflex-theme");
  const selected = themes.some(([id]) => id === saved) ? saved : "mariner";
  const apply = (theme, redraw) => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("fortiflex-theme", theme);
    picker.value = theme;
    if (redraw && typeof loadDashboard === "function") loadDashboard();
  };
  apply(selected, false);
  picker.onchange = (event) => apply(event.target.value, true);

  const themePicker = document.querySelector(".theme-picker");
  if (!themePicker) return;

  const logButton = document.createElement("button");
  logButton.id = "apiLogButton";
  logButton.className = "secondary";
  logButton.textContent = "API Log";
  logButton.hidden = true;
  const sampleButton = document.createElement("button");
  sampleButton.id = "apiSampleButton";
  sampleButton.className = "secondary";
  sampleButton.textContent = "API Sample";
  themePicker.before(logButton, sampleButton);

  const tray = document.createElement("aside");
  tray.id = "apiTray";
  tray.setAttribute("aria-label", "FortiFlex API log");
  tray.innerHTML = `<header><div class="tray-head"><h2>API Log</h2><button class="secondary">Close</button></div><p class="muted" id="apiTrayDescription">Latest successful response per call for this profile. Authentication values are redacted; returned record lists are limited to five and retained only in memory.</p></header><div id="apiSamples" class="muted">No API calls have been captured yet.</div>`;
  document.body.append(tray);
  tray.querySelector("button").onclick = () => tray.classList.remove("open");

  const openTray = async (kind) => {
    const profile = new URLSearchParams(location.search).get("profile") || "";
    const target = tray.querySelector("#apiSamples");
    const title = tray.querySelector("h2");
    const description = tray.querySelector("#apiTrayDescription");
    const isSample = kind === "sample";
    title.textContent = isSample ? "API Sample" : "API Log";
    description.textContent = isSample
      ? "Fabricated FortiFlex examples for demonstration. Authentication values are redacted."
      : "Latest successful response per call for this profile. Authentication values are redacted; returned record lists are limited to five and retained only in memory.";
    tray.classList.add("open");
    target.className = "muted";
    target.textContent = isSample ? "Loading sample…" : "Loading API Log…";
    try {
      const path = isSample ? "/api/debug/sample" : `/api/debug/log?profile=${encodeURIComponent(profile)}`;
      const response = await fetch(path);
      const body = await response.json();
      if (!response.ok) throw Error(body.detail || `Could not load ${isSample ? "API Sample" : "API Log"}`);
      target.replaceChildren();
      if (!body.samples.length) {
        target.className = "muted";
        target.textContent = "No supported API calls have been captured for this profile yet.";
        return;
      }
      body.samples.forEach((sample) => {
        const card = document.createElement("details");
        card.className = "api-sample";
        const heading = document.createElement("summary");
        const records = isSample ? sample.response.sample_records : sample.response.records;
        const recordSummary = sample.response.record_count
          ? ` — ${sample.response.record_count} record(s), showing ${records.length}${sample.response.truncated ? "" : ""}`
          : " — response details";
        heading.textContent = `${sample.operation}${recordSummary}`;
        const detail = document.createElement("pre");
        detail.textContent = JSON.stringify(sample, null, 2);
        card.append(heading, detail);
        target.append(card);
      });
    } catch (error) {
      target.className = "muted";
      target.textContent = error.message;
    }
  };
  logButton.onclick = () => openTray("log");
  sampleButton.onclick = () => openTray("sample");
  fetch(`/api/status?profile=${encodeURIComponent(new URLSearchParams(location.search).get("profile") || "")}`)
    .then((response) => response.ok ? response.json() : null)
    .then((status) => { logButton.hidden = !status || status.sample_mode; })
    .catch(() => {});

})();

// Profile creation lives here so the compact inline dashboard script remains
// backward compatible while this flow can offer a safe choice for orphaned DBs.
(() => {
  const byId = (id) => document.getElementById(id);
  const dialog = byId("newEnvironment");
  if (!dialog) return;
  const menu = dialog.querySelector("menu");
  const createButton = menu.querySelector("button[type='button']");
  const useButton = document.createElement("button");
  useButton.type = "button";
  useButton.className = "secondary hide";
  useButton.textContent = "Use existing database";
  const replaceButton = document.createElement("button");
  replaceButton.type = "button";
  replaceButton.className = "hide";
  replaceButton.textContent = "Replace database";
  menu.insertBefore(useButton, createButton);
  menu.insertBefore(replaceButton, createButton);

  window.openNewEnvironment = () => {
    byId("newSource").value = "program";
    byId("newProfile").value = "";
    byId("newEnvironmentMessage").textContent = "";
    useButton.classList.add("hide");
    replaceButton.classList.add("hide");
    createButton.classList.remove("hide");
    dialog.showModal();
  };

  window.createEnvironment = async (existingDatabase = "error") => {
    const profile = byId("newProfile").value;
    const source = byId("newSource").value;
    const message = byId("newEnvironmentMessage");
    if (existingDatabase === "replace" && !confirm(`Replace the existing local database for ${profile}? Its cached data and local notes cannot be recovered.`)) return;
    try {
      const response = await fetch("/api/profiles", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({profile, source, existing_database: existingDatabase}),
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = result.detail || {};
        if (detail.code === "database_exists") {
          message.textContent = `A local database already exists. Use it unchanged, or replace it with a new ${byId("newSource").selectedOptions[0].text} profile.`;
          useButton.classList.remove("hide");
          replaceButton.classList.remove("hide");
          createButton.classList.add("hide");
          return;
        }
        throw Error(typeof detail === "string" ? detail : detail.message || "Could not create profile");
      }
      location.search = `?profile=${encodeURIComponent(result.id)}`;
    } catch (error) {
      message.textContent = error.message;
    }
  };
  createButton.onclick = () => window.createEnvironment();
  useButton.onclick = () => window.createEnvironment("use");
  replaceButton.onclick = () => window.createEnvironment("replace");
})();
