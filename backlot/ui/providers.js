import { el, getJSON } from "/ui/lib.js";

const THEME_KEY = "backlot.theme";
let currentTheme = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
let state = null;

function applyTheme(theme) {
  currentTheme = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = currentTheme;
  localStorage.setItem(THEME_KEY, currentTheme);
}

function renderThemeToggle() {
  const next = currentTheme === "light" ? "dark" : "light";
  return el("button", {
    class: "theme-toggle",
    type: "button",
    title: `Switch to ${next} theme`,
    "aria-label": `Switch to ${next} theme`,
    "aria-pressed": currentTheme === "light" ? "true" : "false",
    onclick: () => {
      applyTheme(next);
      document.querySelector(".theme-toggle").replaceWith(renderThemeToggle());
    },
  }, el("span", { class: "theme-toggle-icon", "aria-hidden": "true" }, currentTheme === "light" ? "☾" : "☀"));
}

function humanize(value) {
  return String(value || "unknown").replace(/_/g, " ");
}

function buildEnvRows(data) {
  const byName = new Map();
  for (const item of data.env_offers || []) {
    byName.set(item.name, {
      name: item.name,
      configured: Boolean(item.configured),
      unlocks: item.unlocks || [],
    });
  }
  for (const tool of data.tools || []) {
    for (const env of tool.env_vars || []) {
      const existing = byName.get(env.name) || { name: env.name, configured: false, unlocks: [] };
      existing.configured = existing.configured || Boolean(env.configured);
      existing.unlocks.push({
        capability: tool.capability,
        tool: tool.name,
        provider: tool.provider,
        runtime: tool.runtime,
      });
      byName.set(env.name, existing);
    }
  }
  return [...byName.values()].sort((a, b) => (
    Number(a.configured) - Number(b.configured)
    || a.name.localeCompare(b.name)
  ));
}

function statCard(label, value, note, status = "neutral") {
  return el("section", { class: `mini-stat ${status}` },
    el("div", { class: "mini-stat-label" }, label),
    el("div", { class: "mini-stat-value" }, value),
    note ? el("div", { class: "mini-stat-note" }, note) : null,
  );
}

function runtimeChip(name, enabled) {
  return el("span", { class: `runtime-chip ${enabled ? "ok" : "miss"}` },
    el("b", {}, humanize(name)),
    enabled ? "ON" : "OFF",
  );
}

function renderOverview(data) {
  const totals = data.totals || {};
  const ready = Number(totals.configured_tools || 0);
  const totalTools = Number(totals.total_tools || 0);
  const missing = Math.max(0, totalTools - ready);
  const envRows = buildEnvRows(data);
  const configuredEnv = envRows.filter((row) => row.configured).length;
  const missingEnv = Math.max(0, envRows.length - configuredEnv);

  document.getElementById("providerCount").textContent = `${ready}/${totalTools} tools`;
  document.getElementById("overviewMeta").textContent = `${ready} ready, ${missing} missing`;

  const overview = document.getElementById("overview");
  overview.innerHTML = "";
  overview.append(
    statCard("Ready", `${ready}`, `${totalTools} total tools`, "ok"),
    statCard("Missing", `${missing}`, "tools need keys or installs", "warn"),
    statCard("Keys", `${configuredEnv}/${envRows.length}`, `${missingEnv} still missing`, configuredEnv ? "ok" : "warn"),
  );

  const runtime = document.getElementById("runtime");
  runtime.innerHTML = "";
  const chips = el("div", { class: "runtime-row" });
  for (const [name, enabled] of Object.entries(data.composition_runtimes || {})) {
    chips.append(runtimeChip(name, enabled));
  }
  runtime.append(chips);

  for (const warning of data.runtime_warnings || []) {
    runtime.append(el("div", { class: "notice provider-warning" }, el("b", {}, "Warning"), warning));
  }
}

function toolRow(tool) {
  const envVars = tool.env_vars || [];
  return el("details", { class: `provider-item ${tool.status === "available" ? "ok" : "miss"}` },
    el("summary", {},
      el("span", { class: `provider-dot ${tool.status === "available" ? "ok" : "miss"}` }),
      el("span", { class: "item-main" },
        el("b", {}, tool.name),
        el("small", {}, `${humanize(tool.provider)} · ${humanize(tool.capability)}`),
      ),
      el("span", { class: "chip" }, humanize(tool.runtime)),
      el("span", { class: `provider-status ${tool.status === "available" ? "ok" : "miss"}` },
        tool.status === "available" ? "AVAILABLE" : "MISSING"),
    ),
    el("div", { class: "item-detail" },
      tool.best_for ? el("p", {}, tool.best_for) : null,
      envVars.length ? el("div", { class: "item-chips" },
        envVars.map((env) => el("span", { class: `env-pill ${env.configured ? "ok" : "miss"}` },
          `${env.name}: ${env.configured ? "SET" : "MISSING"}`,
        )),
      ) : null,
      tool.install_instructions ? el("pre", {}, tool.install_instructions) : null,
    ),
  );
}

function envRow(item) {
  const unique = [];
  const seen = new Set();
  for (const unlock of item.unlocks || []) {
    const key = `${unlock.capability}:${unlock.tool}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(unlock);
  }
  return el("details", { class: `provider-item ${item.configured ? "ok" : "miss"}` },
    el("summary", {},
      el("span", { class: `provider-dot ${item.configured ? "ok" : "miss"}` }),
      el("span", { class: "item-main" },
        el("b", {}, item.name),
        el("small", {}, `${unique.length} tools depend on it`),
      ),
      el("span", { class: "chip" }, item.configured ? "SET" : "MISSING"),
      el("span", { class: `provider-status ${item.configured ? "ok" : "miss"}` },
        item.configured ? "READY" : "NEEDED"),
    ),
    el("div", { class: "item-detail" },
      unique.length ? el("div", { class: "item-chips" },
        unique.slice(0, 5).map((u) => el("span", { class: "chip" }, u.tool)),
        unique.length > 5 ? el("span", { class: "chip" }, `+${unique.length - 5}`) : null,
      ) : null,
    ),
  );
}

function capabilityCard(capability) {
  const configured = Number(capability.configured || 0);
  const total = Number(capability.total || 0);
  const pct = total ? Math.round((configured / total) * 100) : 0;
  return el("section", { class: "provider-stat" },
    el("div", { class: "provider-stat-top" },
      el("span", { class: "provider-stat-name" }, humanize(capability.capability)),
      el("span", { class: `provider-status ${configured ? "ok" : "miss"}` }, `${configured}/${total}`),
    ),
    el("div", { class: "provider-meter" }, el("i", { style: `width:${pct}%` })),
    el("div", { class: "provider-stat-meta" },
      capability.available_providers?.length
        ? capability.available_providers.join(", ")
        : "no provider configured",
    ),
  );
}

function renderReady(data) {
  const rows = (data.tools || []).filter((tool) => tool.status === "available");
  document.getElementById("readyCount").textContent = `${rows.length} shown`;
  const list = document.getElementById("readyList");
  list.innerHTML = "";
  if (!rows.length) {
    list.append(el("div", { class: "empty" }, el("div", { class: "big" }, "NO READY TOOLS")));
    return;
  }
  for (const tool of rows) list.append(toolRow(tool));
}

function renderEnv(data) {
  const rows = buildEnvRows(data);
  document.getElementById("envCount").textContent = `${rows.length} keys`;
  const grid = document.getElementById("envGrid");
  grid.innerHTML = "";
  if (!rows.length) {
    grid.append(el("div", { class: "empty" }, el("div", { class: "big" }, "NO KEYS")));
    return;
  }
  for (const row of rows) grid.append(envRow(row));
}

function renderAdvanced(data) {
  const summary = document.getElementById("summary");
  summary.innerHTML = "";
  for (const cap of data.capabilities || []) summary.append(capabilityCard(cap));
}

async function render() {
  document.getElementById("providerStatus").textContent = "LOADING";
  state = await getJSON("/api/providers");
  document.getElementById("providerStatus").textContent = "READ ONLY";
  renderOverview(state);
  renderReady(state);
  renderEnv(state);
  renderAdvanced(state);
}

applyTheme(currentTheme);
document.querySelector(".slate .spacer").before(renderThemeToggle());
document.getElementById("refreshProviders").addEventListener("click", () => {
  render().catch((err) => {
    document.getElementById("providerStatus").textContent = "ERROR";
    console.error(err);
  });
});

render().catch((err) => {
  document.getElementById("providerStatus").textContent = "ERROR";
  document.getElementById("overview").append(el("div", { class: "notice" }, el("b", {}, "ERROR"), String(err)));
  console.error(err);
});
