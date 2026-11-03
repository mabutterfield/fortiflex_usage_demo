(() => {
  const picker = document.getElementById("theme");
  if (!picker) return;

  const themes = [
    ["mariner", "Mariner"],
    ["retro", "Retro"],
    ["dark-matter", "Dark Matter"],
    ["onyx", "Onyx"],
    ["eclipse", "Eclipse"],
  ];
  const allowed = new Set(themes.map(([id]) => id));
  const saved = localStorage.getItem("fortiflex-theme");
  const selected = allowed.has(saved) ? saved : "mariner";

  picker.innerHTML = themes
    .map(([id, label]) => `<option value="${id}">${label}</option>`)
    .join("");

  // Convert the retired Documentation/Neutrino preference the first time it is seen.
  setFortiTheme(selected, false);
  picker.onchange = (event) => setFortiTheme(event.target.value, true);
})();
