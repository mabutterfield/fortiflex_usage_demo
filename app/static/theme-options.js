(() => {
  const themes = [
    ["mariner", "Mariner"],
    ["retro", "Retro"],
    ["dark-matter", "Dark Matter"],
    ["onyx", "Onyx"],
    ["eclipse", "Eclipse"],
  ];
  const css = `
    [data-theme=mariner]{--page:#eef2f5;--surface:#fff;--text:#17233a;--muted:#587085;--header:#1268b3;--button:#1769aa;--button-alt:#60798e;--border:#ccd8e3;--grid:#d8e4ee;--link:#1769aa;--metric:#37a3dd;--canvas:#fafcff;--tip:#17233a}
    [data-theme=dark-matter]{--page:#202020;--surface:#272727;--text:#d2d2d2;--muted:#999;--header:#454545;--button:#6865aa;--button-alt:#444;--border:#3a3a3a;--grid:#3a3a3a;--link:#918cd1;--metric:#6b68ad;--canvas:#252525;--tip:#141414;--shadow:#00000044;--good-bg:#403d68;--good-text:#e1ddff;--bad-bg:#60343d;--bad-text:#ffd9dc;--outside:#3a3a3a;--unavailable:#303030}
    [data-theme=onyx]{--page:#202020;--surface:#272727;--text:#d2d2d2;--muted:#999;--header:#454545;--button:#46955c;--button-alt:#444;--border:#3a3a3a;--grid:#3a3a3a;--link:#58b674;--metric:#46955c;--canvas:#252525;--tip:#141414;--shadow:#00000044;--good-bg:#245234;--good-text:#d3f0da;--bad-bg:#60343d;--bad-text:#ffd9dc;--outside:#3a3a3a;--unavailable:#303030}
    [data-theme=eclipse]{--page:#202020;--surface:#272727;--text:#d2d2d2;--muted:#999;--header:#454545;--button:#ec9300;--button-alt:#444;--border:#3a3a3a;--grid:#3a3a3a;--link:#ffae2d;--metric:#ec9300;--canvas:#252525;--tip:#141414;--shadow:#00000044;--good-bg:#554526;--good-text:#ffebc3;--bad-bg:#60343d;--bad-text:#ffd9dc;--outside:#3a3a3a;--unavailable:#303030}
    [data-theme=retro]{--page:#d5e4e5;--surface:#e5f0f1;--text:#294e4c;--muted:#6c8888;--header:#bdd2d3;--button:#168983;--button-alt:#6c9090;--border:#bad0d0;--grid:#c5d9d9;--link:#087b76;--metric:#168983;--canvas:#e9f3f4;--tip:#1d5552;--shadow:#79999a55;--good-bg:#c5e6db;--good-text:#155f50;--bad-bg:#f1d2d2;--bad-text:#892b2b;--outside:#cadada;--unavailable:#e1ebeb}
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
})();
