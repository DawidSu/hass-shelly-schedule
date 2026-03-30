/**
 * Shelly Schedule Card
 * A custom Lovelace card for managing Shelly device schedules.
 * Registers with window.customCards so it appears in the HA card picker.
 */

const DAYS_OPTIONS = [
  "Täglich",
  "Werktags (Mo-Fr)",
  "Wochenende (Sa-So)",
  "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag",
];

const ACTION_OPTIONS = [
  "Einschalten", "Ausschalten",
  "Öffnen", "Schließen", "Stoppen", "Position",
];

const DAYS_MAP = {
  "Täglich": "*",
  "Werktags (Mo-Fr)": "MON,TUE,WED,THU,FRI",
  "Wochenende (Sa-So)": "SAT,SUN",
  "Montag": "MON", "Dienstag": "TUE", "Mittwoch": "WED",
  "Donnerstag": "THU", "Freitag": "FRI",
  "Samstag": "SAT", "Sonntag": "SUN",
};

const DAY_ORDER = ["MON","TUE","WED","THU","FRI","SAT","SUN"];
const DAY_LABEL = { MON:"Mo", TUE:"Di", WED:"Mi", THU:"Do", FRI:"Fr", SAT:"Sa", SUN:"So" };

function daysToActiveSet(daysVal) {
  const mapped = DAYS_MAP[daysVal];
  if (!daysVal || daysVal === "Täglich" || mapped === "*") return new Set(DAY_ORDER);
  const src = mapped || daysVal;
  return new Set(src.split(",").map(d => d.trim().toUpperCase()).filter(d => DAY_LABEL[d]));
}

function renderDayChips(daysVal) {
  const active = daysToActiveSet(daysVal);
  return DAY_ORDER.map(d =>
    `<span class="day-chip${active.has(d) ? " active" : ""}">${DAY_LABEL[d]}</span>`
  ).join("");
}

function parseCron(timespec) {
  const ts = (timespec || "").trim();

  // Shelly sunrise/sunset format: @sunset-0h10m * * SUN,MON,...
  // Also handles: @sunrise, @sunrise+30 (our format), @sunrise+0h30m
  // Regex captures: type, optional sign+hours+minutes or sign+plain-minutes, trailing fields
  const sunMatch = ts.match(/^@(sunrise|sunset)(?:([+-])(?:(\d+)h)?(\d+)m|([+-]\d+))?(?:\s+(.*))?$/i);
  if (sunMatch) {
    const type = sunMatch[1].toLowerCase();
    let offset = 0;
    if (sunMatch[2]) {
      // Shelly format: +/-Xh Ym
      const sign  = sunMatch[2] === "-" ? -1 : 1;
      const hours = parseInt(sunMatch[3] || "0");
      const mins  = parseInt(sunMatch[4] || "0");
      offset = sign * (hours * 60 + mins);
    } else if (sunMatch[5]) {
      // Our plain-minutes format: +30 or -10
      offset = parseInt(sunMatch[5]);
    }
    // Parse weekday from trailing cron fields: "mday month wday"
    const trailing = (sunMatch[6] || "").trim().split(/\s+/);
    const dayPart  = trailing[2] || "*";
    let days = "Täglich";
    if (dayPart !== "*") {
      // Check if it's all 7 days listed explicitly
      const ALL7 = new Set(["SUN","MON","TUE","WED","THU","FRI","SAT"]);
      const given = new Set(dayPart.split(",").map(d => d.trim().toUpperCase()));
      if ([...ALL7].every(d => given.has(d))) {
        days = "Täglich";
      } else {
        for (const [label, val] of Object.entries(DAYS_MAP)) {
          if (val.toUpperCase() === dayPart.toUpperCase()) { days = label; break; }
        }
        if (days === "Täglich") days = dayPart;
      }
    }
    return { timeType: type, offset, time: null, days };
  }

  // Regular cron: "0 <min> <hour> * * <days>"
  const parts = ts.split(" ");
  if (parts.length < 3) return { timeType: "time", time: "?", days: "?" };
  const hour = parts[2].padStart(2, "0");
  const min  = parts[1].padStart(2, "0");
  const dayPart = parts.slice(5).join(" ") || "*";
  // Normalize day order for DAYS_MAP lookup (Shelly may return SUN,SAT instead of SAT,SUN)
  const daySet  = new Set(dayPart.split(",").map(d => d.trim().toUpperCase()));
  const ALL7    = new Set(["MON","TUE","WED","THU","FRI","SAT","SUN"]);
  if (dayPart === "*" || [...ALL7].every(d => daySet.has(d))) {
    return { timeType: "time", time: `${hour}:${min}`, days: "Täglich" };
  }
  const normDay = [...daySet].sort().join(",");
  let dayLabel = dayPart; // fallback: raw value
  for (const [label, val] of Object.entries(DAYS_MAP)) {
    const normVal = val.split(",").map(d => d.trim().toUpperCase()).sort().join(",");
    if (normVal === normDay) { dayLabel = label; break; }
  }
  return { timeType: "time", time: `${hour}:${min}`, days: dayLabel };
}

function callPart(c) {
  const m = (c.method || "").toLowerCase();
  if (m.includes("switch.set")) return c.params?.on ? "Einschalten" : "Ausschalten";
  if (m.includes("cover.open")) return "Öffnen";
  if (m.includes("cover.close")) return "Schließen";
  if (m.includes("cover.stop")) return "Stoppen";
  if (m.includes("gotoposition")) return `Position ${c.params?.pos ?? "?"}%`;
  return m;
}

function callIcon(c) {
  const m = (c.method || "").toLowerCase();
  if (m.includes("switch.set")) return c.params?.on ? "mdi:power" : "mdi:power-off";
  if (m.includes("cover.open")) return "mdi:arrow-up-circle";
  if (m.includes("cover.close")) return "mdi:arrow-down-circle";
  if (m.includes("cover.stop")) return "mdi:stop-circle";
  if (m.includes("gotoposition")) return "mdi:percent-circle";
  return "mdi:calendar-clock";
}

class ShellyScheduleCard extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._attached = false;
    this._modal = null;
    this._editJob = null;  // null = create, object = edit
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
    this._config = config || {};
    if (this._attached) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._attached) {
      this._attached = true;
      this._render();
    } else {
      this._updateContent();
    }
  }

  connectedCallback() {
    if (this._hass && !this._attached) {
      this._attached = true;
      this._render();
    }
  }

  // ── Styles ────────────────────────────────────────────────────────────────

  _css() {
    return `
      :host { display: block; }
      ha-card { padding: 0; overflow: hidden; }
      .card-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px 8px;
        font-size: 1.1em; font-weight: 600;
        color: var(--primary-text-color);
        border-bottom: 1px solid var(--divider-color);
      }
      .card-header .title { display: flex; align-items: center; gap: 8px; }
      .card-header .icon { --mdc-icon-size: 22px; color: var(--primary-color); }
      .toolbar {
        display: flex; align-items: center; gap: 8px;
        padding: 8px 16px;
        background: var(--secondary-background-color);
        border-bottom: 1px solid var(--divider-color);
        flex-wrap: wrap;
      }
      .toolbar select, .toolbar input {
        flex: 1; min-width: 120px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 6px;
        padding: 6px 8px;
        font-size: 0.9em;
      }
      .btn {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 6px 12px; border: none; border-radius: 6px;
        font-size: 0.85em; font-weight: 500; cursor: pointer;
        transition: filter 0.15s;
      }
      .btn:hover { filter: brightness(1.1); }
      .btn-primary { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .btn-danger  { background: var(--error-color, #d32f2f); color: #fff; }
      .btn-secondary { background: var(--secondary-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); }
      .btn-icon { background: transparent; border: none; cursor: pointer; color: var(--secondary-text-color); padding: 4px; border-radius: 4px; }
      .btn-icon:hover { color: var(--primary-color); background: var(--secondary-background-color); }

      .schedule-list { padding: 0; list-style: none; margin: 0; }
      .schedule-item {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 16px;
        border-bottom: 1px solid var(--divider-color);
      }
      .schedule-item:last-child { border-bottom: none; }
      .schedule-item.disabled { opacity: 0.5; }
      .sched-id {
        min-width: 24px; height: 24px; border-radius: 50%;
        background: var(--primary-color); color: var(--text-primary-color, #fff);
        display: flex; align-items: center; justify-content: center;
        font-size: 0.75em; font-weight: 700; flex-shrink: 0;
      }
      .sched-id ha-icon { --mdc-icon-size: 14px; }
      .sched-id.disabled { background: var(--disabled-color, #bbb); }
      .sched-info { flex: 1; min-width: 0; }
      .sched-time { font-weight: 600; font-size: 1em; color: var(--primary-text-color); }
      .sched-details { font-size: 0.8em; color: var(--secondary-text-color); margin-top: 2px; }
      .day-chips { display: flex; gap: 3px; flex-wrap: wrap; }
      .day-chip {
        font-size: 0.7em; font-weight: 600; padding: 1px 5px; border-radius: 4px;
        background: var(--secondary-background-color); color: var(--disabled-color, #bbb);
      }
      .day-chip.active { background: var(--primary-color); color: var(--text-primary-color, #fff); }
      .sched-actions { display: flex; gap: 4px; }

      .empty-state {
        padding: 24px 16px; text-align: center;
        color: var(--secondary-text-color); font-size: 0.95em;
      }
      .device-selector { padding: 8px 16px; }
      .device-selector select {
        width: 100%;
        background: var(--card-background-color); color: var(--primary-text-color);
        border: 1px solid var(--divider-color); border-radius: 6px;
        padding: 8px 10px; font-size: 0.95em;
      }

      /* Modal */
      .modal-backdrop {
        position: fixed; inset: 0; z-index: 9999;
        background: rgba(0,0,0,0.5);
        display: flex; align-items: center; justify-content: center;
      }
      .modal {
        background: var(--card-background-color); color: var(--primary-text-color);
        border-radius: 12px; padding: 24px; min-width: 300px; max-width: 420px; width: 90%;
        box-shadow: 0 8px 32px rgba(0,0,0,0.3);
      }
      .modal h3 { margin: 0 0 16px; font-size: 1.1em; }
      .form-row { margin-bottom: 12px; }
      .form-row label { display: block; font-size: 0.85em; color: var(--secondary-text-color); margin-bottom: 4px; }
      .form-row input, .form-row select {
        width: 100%; box-sizing: border-box;
        background: var(--secondary-background-color); color: var(--primary-text-color);
        border: 1px solid var(--divider-color); border-radius: 6px;
        padding: 8px 10px; font-size: 0.95em;
      }
      .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
      .toggle-enable { display: flex; align-items: center; gap: 8px; font-size: 0.9em; }

      /* Toggle switch */
      .sw-toggle { position: relative; display: inline-block; width: 36px; height: 20px; flex-shrink: 0; cursor: pointer; }
      .sw-toggle input { opacity: 0; width: 0; height: 0; position: absolute; }
      .sw-slider {
        position: absolute; inset: 0; border-radius: 20px;
        background: var(--disabled-color, #bbb);
        transition: background 0.2s;
      }
      .sw-slider::before {
        content: ""; position: absolute;
        width: 14px; height: 14px; border-radius: 50%;
        background: #fff; left: 3px; top: 3px;
        transition: transform 0.2s;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
      }
      .sw-toggle input:checked + .sw-slider { background: var(--primary-color, #03a9f4); }
      .sw-toggle input:checked + .sw-slider::before { transform: translateX(16px); }

      .status-bar {
        padding: 6px 16px; font-size: 0.8em;
        color: var(--secondary-text-color);
        background: var(--secondary-background-color);
        border-top: 1px solid var(--divider-color);
      }
    `;
  }

  // ── Main render ───────────────────────────────────────────────────────────

  _render() {
    const icon      = this._config.icon;
    const color     = this._config.color      || "var(--primary-color)";
    const title     = this._config.title      || "Shelly Schedules";
    const hideTitle = !!this._config.hide_title;
    this.shadowRoot.innerHTML = `
      <style>${this._css()}</style>
      <ha-card>
        ${hideTitle ? "" : `
        <div class="card-header">
          <div class="title">
            ${icon ? `<ha-icon class="icon" icon="${icon}" style="color:${color};"></ha-icon>` : ""}
            <span>${title}</span>
          </div>
        </div>`}
        <div id="card-body"></div>
      </ha-card>
    `;
    // Bind events exactly once on the persistent container
    const body = this.shadowRoot.getElementById("card-body");
    this._bindEvents(body);
    this._updateContent();
  }

  _updateContent() {
    const body = this.shadowRoot.getElementById("card-body");
    if (!body || !this._hass) return;

    const configuredEntity = this._config.entity;

    if (!configuredEntity) {
      body.innerHTML = `<div class="empty-state">Bitte eine Entität unter <b>Bearbeiten</b> auswählen.</div>`;
      return;
    }

    const state = this._hass.states[configuredEntity];
    if (!state) {
      body.innerHTML = `<div class="empty-state">Entität <b>${configuredEntity}</b> nicht gefunden.</div>`;
      return;
    }

    const isGen1 = configuredEntity.startsWith("sensor.shelly_gen1_");
    const autoName = state.attributes?.friendly_name?.replace(" Schedule", "") || configuredEntity;
    const cfgName = this._config.device_name;
    const name = this._resolveDeviceName(cfgName, configuredEntity) || autoName;
    const dev = { entityId: configuredEntity, name, state };

    body.innerHTML = this._renderDevice(dev, isGen1 ? "gen1" : "gen2");
  }

  _getGen2Devices() {
    const devices = [];
    for (const [eid, state] of Object.entries(this._hass.states)) {
      if (
        eid.startsWith("sensor.shelly_") &&
        eid.endsWith("_schedule") &&
        !eid.startsWith("sensor.shelly_gen1_")
      ) {
        const name = state.attributes?.friendly_name?.replace(" Schedule", "") || eid;
        devices.push({ entityId: eid, name, state });
      }
    }
    return devices.sort((a, b) => a.name.localeCompare(b.name));
  }

  _getGen1Devices() {
    const devices = [];
    for (const [eid, state] of Object.entries(this._hass.states)) {
      if (eid.startsWith("sensor.shelly_gen1_") && eid.endsWith("_schedule")) {
        const name = state.attributes?.friendly_name?.replace(" Schedule", "") || eid;
        devices.push({ entityId: eid, name, state });
      }
    }
    return devices.sort((a, b) => a.name.localeCompare(b.name));
  }

  _renderSection(type, devices) {
    const label = type === "gen1" ? "Gen1 Geräte" : "Gen2/Gen3 Geräte";
    let html = `<div style="padding:6px 16px 2px;font-size:0.75em;font-weight:600;color:var(--secondary-text-color);text-transform:uppercase;letter-spacing:.05em;">${label}</div>`;

    for (const dev of devices) {
      html += this._renderDevice(dev, type);
    }
    return html;
  }

  _renderDevice(dev, type) {
    const jobs = dev.state?.attributes?.jobs || dev.state?.attributes?.schedule_rules || [];
    const isUnavailable = dev.state?.state === "unavailable";
    const isGen1 = type === "gen1";
    const hostname = dev.state?.attributes?.hostname;
    const webLink = (hostname && this._config?.hide_webui !== true)
      ? `<button class="btn-webui" data-entity="${dev.entityId}" data-hostname="${hostname}"
           style="display:inline-flex;align-items:center;gap:3px;font-size:0.75em;color:var(--primary-color);background:none;border:none;padding:2px 4px;cursor:pointer;border-radius:4px;line-height:1;"
           title="Web-UI öffnen"><svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:currentColor;flex-shrink:0;pointer-events:none;" aria-hidden="true"><path d="M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7zm-2 16H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-7h-2v7z"/></svg> Web-UI</button>`
      : "";

    let html = `
      <div class="device-block" data-entity="${dev.entityId}" data-type="${type}">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 16px 4px;background:var(--secondary-background-color);border-bottom:1px solid var(--divider-color);">
          <div style="display:flex;align-items:center;gap:8px;">
            ${this._config?.device_icon ? `<ha-icon icon="${this._config.device_icon}" style="--mdc-icon-size:18px;color:${this._config.color || "var(--primary-color)"};flex-shrink:0;"></ha-icon>` : ""}
            <span style="font-weight:600;font-size:0.95em;">${dev.name}</span>
            ${webLink}
          </div>
          <div style="display:flex;gap:4px;align-items:center;">
            ${isUnavailable ? '<span style="font-size:0.75em;color:var(--error-color);">Nicht erreichbar</span>' : `<span style="font-size:0.75em;color:var(--secondary-text-color);">${jobs.length} ${jobs.length !== 1 ? "Aufgaben" : "Aufgabe"}</span>`}
            ${!isGen1 ? `<button class="btn btn-primary btn-add" data-entity="${dev.entityId}" style="padding:4px 8px;font-size:0.8em;">+ Neu</button>` : ""}
          </div>
        </div>
    `;

    if (!isUnavailable && jobs.length > 0) {
      html += `<ul class="schedule-list">`;
      for (const job of (isGen1 ? jobs : jobs)) {
        html += isGen1 ? this._renderGen1Rule(job, dev) : this._renderGen2Job(job, dev);
      }
      html += `</ul>`;
    } else if (!isUnavailable) {
      html += `<div class="empty-state" style="padding:12px 16px;">Keine Zeitpläne</div>`;
    }

    html += `</div>`;
    return html;
  }

  _renderGen2Job(job, dev) {
    const parsed = parseCron(job.timespec);
    let timeDisplay;
    if (parsed.timeType === "sunrise") {
      const off = parsed.offset;
      timeDisplay = "☀️ Sonnenaufgang" + (off > 0 ? ` +${off}min` : off < 0 ? ` ${off}min` : "");
    } else if (parsed.timeType === "sunset") {
      const off = parsed.offset;
      timeDisplay = "🌙 Sonnenuntergang" + (off > 0 ? ` +${off}min` : off < 0 ? ` ${off}min` : "");
    } else {
      timeDisplay = parsed.time;
    }
    const days   = parsed.days;
    const action = (job.calls || []).map(callPart).join(", ");
    const daysHtml = this._config?.day_display === "chips"
      ? `<div class="day-chips">${renderDayChips(days)}</div>`
      : days;
    const enabled = job.enable !== false;
    const firstCall = (job.calls || [])[0];
    const badgeMode = this._config?.badge_mode ?? "id";
    const badge = badgeMode === "none" ? "" :
      badgeMode === "icon" && firstCall ? `<ha-icon icon="${callIcon(firstCall)}"></ha-icon>` :
      job.id;
    return `
      <li class="schedule-item ${enabled ? "" : "disabled"}" data-job-id="${job.id}" data-entity="${dev.entityId}">
        ${badgeMode !== "none" ? `<div class="sched-id ${enabled ? "" : "disabled"}">${badge}</div>` : ""}
        <div class="sched-info">
          <div class="sched-time">${timeDisplay}</div>
          <div class="sched-details">${daysHtml}${this._config?.hide_action ? "" : " · " + action}</div>
        </div>
        <div class="sched-actions">
          <label class="sw-toggle" title="${enabled ? "Deaktivieren" : "Aktivieren"}">
            <input type="checkbox" class="btn-toggle" ${enabled ? "checked" : ""} data-id="${job.id}" data-entity="${dev.entityId}" data-enabled="${enabled}">
            <span class="sw-slider"></span>
          </label>
          ${this._config?.hide_run_button ? "" : `<button class="btn-icon btn-test" title="Jetzt ausführen" data-calls='${JSON.stringify(job.calls || []).replace(/'/g, "&#39;")}' data-entity="${dev.entityId}"><ha-icon icon="mdi:play-circle-outline"></ha-icon></button>`}
          <button class="btn-icon btn-edit" title="Bearbeiten" data-job='${JSON.stringify(job).replace(/'/g, "&#39;")}' data-entity="${dev.entityId}">
            <ha-icon icon="mdi:pencil"></ha-icon>
          </button>
          <button class="btn-icon btn-delete" title="Löschen" data-id="${job.id}" data-entity="${dev.entityId}">
            <ha-icon icon="mdi:delete"></ha-icon>
          </button>
        </div>
      </li>
    `;
  }

  _renderGen1Rule(rule, dev) {
    // Gen1 rule format: "MM HH * * *=on"
    const [cron, action] = (rule || "").split("=");
    const parts = (cron || "").trim().split(" ");
    const hour = (parts[1] || "?").padStart(2, "0");
    const min = (parts[0] || "?").padStart(2, "0");
    const gen1BadgeMode = this._config?.badge_mode ?? "id";
    const gen1Badge = gen1BadgeMode === "none" ? "" :
      gen1BadgeMode === "icon" ? `<ha-icon icon="${action === "on" ? "mdi:power" : "mdi:power-off"}"></ha-icon>` :
      "·";
    return `
      <li class="schedule-item" data-entity="${dev.entityId}">
        ${gen1BadgeMode !== "none" ? `<div class="sched-id">${gen1Badge}</div>` : ""}
        <div class="sched-info">
          <div class="sched-time">${hour}:${min}</div>
          <div class="sched-details">${this._config?.hide_action ? "" : (action === "on" ? "Einschalten" : "Ausschalten")}</div>
        </div>
      </li>
    `;
  }

  // ── Event binding ─────────────────────────────────────────────────────────

  _bindEvents(body) {
    // Single delegated click handler — bound ONCE, reads live data from this._hass at click time
    body.addEventListener("click", e => {
      // Web-UI button
      const webBtn = e.target.closest(".btn-webui");
      if (webBtn) {
        const entityId = webBtn.dataset.entity;
        const hostname = webBtn.dataset.hostname;
        // Open URL first — clipboard.writeText() consumes the browser's
        // transient activation token, which would block window.open afterwards
        window.open(`http://${hostname}`, "_blank");
        const password = this._hass?.states[entityId]?.attributes?.login_password;
        if (password && navigator.clipboard) navigator.clipboard.writeText(password).catch(() => {});
        return;
      }

      // Add new schedule
      const addBtn = e.target.closest(".btn-add");
      if (addBtn) {
        const entityId = addBtn.dataset.entity;
        const state = this._hass?.states[entityId];
        const name = state?.attributes?.friendly_name?.replace(" Schedule", "") || entityId;
        this._openModal(null, { entityId, name, state });
        return;
      }

      // Test action
      const testBtn = e.target.closest(".btn-test");
      if (testBtn) {
        const deviceName = this._entityToDeviceName(testBtn.dataset.entity);
        try {
          const calls = JSON.parse(testBtn.dataset.calls.replace(/&#39;/g, "'"));
          this._callService("run_action", { device: deviceName, calls });
        } catch (err) { console.error("parse calls", err); }
        return;
      }

      // Edit
      const editBtn = e.target.closest(".btn-edit");
      if (editBtn) {
        const entityId = editBtn.dataset.entity;
        const state = this._hass?.states[entityId];
        const name = state?.attributes?.friendly_name?.replace(" Schedule", "") || entityId;
        try {
          const job = JSON.parse(editBtn.dataset.job.replace(/&#39;/g, "'"));
          this._openModal(job, { entityId, name, state });
        } catch (err) { console.error("parse job", err); }
        return;
      }

      // Delete
      const delBtn = e.target.closest(".btn-delete");
      if (delBtn) {
        const id = parseInt(delBtn.dataset.id);
        const deviceName = this._entityToDeviceName(delBtn.dataset.entity);
        if (confirm(`Aufgabe #${id} wirklich löschen?`)) {
          this._callService("delete_schedule", { device: deviceName, schedule_id: id });
        }
        return;
      }
    });

    // Toggle enable/disable (change event, not click)
    body.addEventListener("change", e => {
      const input = e.target.closest(".btn-toggle");
      if (!input) return;
      const id = parseInt(input.dataset.id);
      const deviceName = this._entityToDeviceName(input.dataset.entity);
      this._callService(input.checked ? "enable_schedule" : "disable_schedule", {
        device: deviceName,
        schedule_id: id,
      });
    });
  }

  // ── Modal ─────────────────────────────────────────────────────────────────

  _openModal(job, dev) {
    this._editJob = job;

    const isEdit  = job !== null;
    const parsed  = isEdit ? parseCron(job.timespec) : { timeType: "time", time: "07:00", days: "Täglich", offset: 0 };
    const timeType = parsed.timeType || "time";
    const time     = parsed.time || "07:00";
    const days     = parsed.days || "Täglich";
    const sunOffset = parsed.offset || 0;
    const profile = this._hass?.states[dev.entityId]?.attributes?.device_profile
      || this._getDeviceProfileFromHass(dev.entityId);
    const isCover = profile === "cover";

    const action = isEdit && job.calls?.length
      ? callPart(job.calls[0]).split(" ")[0]
      : (isCover ? "Öffnen" : "Einschalten");
    const enabled = isEdit ? (job.enable !== false) : true;
    const pos = isEdit && job.calls?.[0]?.params?.pos != null ? job.calls[0].params.pos : 50;

    const availableActions = isCover
      ? ["Öffnen", "Schließen", "Stoppen", "Position"]
      : ["Einschalten", "Ausschalten"];

    const timeTypeOpts = [
      ["time",    "Uhrzeit"],
      ["sunrise", "☀️ Sonnenaufgang"],
      ["sunset",  "🌙 Sonnenuntergang"],
    ].map(([v, l]) => `<option value="${v}" ${v === timeType ? "selected" : ""}>${l}</option>`).join("");

        // Convert parsed days label / raw cron string → Set of cron day codes
    const WDAYS = [
      { label: "Mo", cron: "MON" }, { label: "Di", cron: "TUE" },
      { label: "Mi", cron: "WED" }, { label: "Do", cron: "THU" },
      { label: "Fr", cron: "FRI" }, { label: "Sa", cron: "SAT" },
      { label: "So", cron: "SUN" },
    ];
    const ALL_CRON = new Set(WDAYS.map(d => d.cron));
    function daysToSet(daysVal) {
      const mapped = DAYS_MAP[daysVal]; // e.g. "*", "MON,TUE,WED,THU,FRI"
      if (mapped === "*" || mapped == null && (daysVal === "Täglich" || !daysVal)) return new Set(ALL_CRON);
      if (mapped) return new Set(mapped.split(",").map(d => d.trim().toUpperCase()));
      // Raw cron string fallback (e.g. "SUN,SAT" when DAYS_MAP had no match)
      const parts = daysVal.split(",").map(d => d.trim().toUpperCase()).filter(d => ALL_CRON.has(d));
      return parts.length > 0 ? new Set(parts) : new Set(ALL_CRON);
    }
    const checkedSet = daysToSet(days);
    const dayCheckboxes = WDAYS.map(d =>
      `<label style="display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer;font-size:0.82em;user-select:none;">
        <input type="checkbox" class="m-day-cb" data-cron="${d.cron}" ${checkedSet.has(d.cron) ? "checked" : ""} style="cursor:pointer;width:16px;height:16px;accent-color:var(--primary-color);">
        ${d.label}
      </label>`
    ).join("");
    const actionOpts = availableActions.map(a =>
      `<option value="${a}" ${a === action ? "selected" : ""}>${a}</option>`
    ).join("");

    const S = {
      backdrop: `position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.55);display:flex;align-items:center;justify-content:center;`,
      modal:    `background:var(--card-background-color,#1e2030);color:var(--primary-text-color,#cdd6f4);border-radius:12px;padding:24px;min-width:300px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4);`,
      h3:       `margin:0 0 16px;font-size:1.1em;`,
      row:      `margin-bottom:12px;`,
      label:    `display:block;font-size:0.85em;color:var(--secondary-text-color,#a6adc8);margin-bottom:4px;`,
      field:    `width:100%;box-sizing:border-box;background:var(--secondary-background-color,#252535);color:var(--primary-text-color,#cdd6f4);border:1px solid var(--divider-color,#444);border-radius:6px;padding:8px 10px;font-size:0.95em;`,
      actions:  `display:flex;justify-content:flex-end;gap:8px;margin-top:20px;`,
      btnSec:   `padding:6px 14px;border:1px solid var(--divider-color,#444);border-radius:6px;background:var(--secondary-background-color,#252535);color:var(--primary-text-color,#cdd6f4);cursor:pointer;font-size:0.9em;`,
      btnPri:   `padding:6px 14px;border:none;border-radius:6px;background:var(--primary-color,#03a9f4);color:#fff;cursor:pointer;font-size:0.9em;font-weight:600;`,
      toggle:   `display:flex;align-items:center;gap:8px;font-size:0.9em;margin-bottom:4px;`,
    };

    const isSun = timeType === "sunrise" || timeType === "sunset";
    const backdrop = document.createElement("div");
    backdrop.style.cssText = S.backdrop;
    backdrop.innerHTML = `
      <div style="${S.modal}">
        <h3 style="${S.h3}">${isEdit ? "Aufgabe bearbeiten" : "Neue Aufgabe"} – ${dev.name}</h3>
        <div style="${S.row}">
          <label style="${S.label}">Zeittyp</label>
          <select id="m-timetype" style="${S.field}">${timeTypeOpts}</select>
        </div>
        <div id="m-time-row" style="${S.row}display:${isSun ? "none" : "block"}">
          <label style="${S.label}">Uhrzeit</label>
          <input type="time" id="m-time" value="${time}" style="${S.field}">
        </div>
        <div id="m-sun-row" style="${S.row}display:${isSun ? "block" : "none"}">
          <label style="${S.label}">Versatz (Minuten, negativ = davor)</label>
          <input type="number" id="m-offset" min="-120" max="120" step="5" value="${sunOffset}" style="${S.field}">
        </div>
        <div id="m-days-row" style="${S.row}display:block">
          <label style="${S.label}">Wochentage</label>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">${dayCheckboxes}</div>
        </div>
        <div style="${S.row}">
          <label style="${S.label}">Aktion</label>
          <select id="m-action" style="${S.field}">${actionOpts}</select>
        </div>
        <div id="pos-row" style="${S.row}display:${action === "Position" ? "block" : "none"}">
          <label style="${S.label}">Position (%)</label>
          <input type="number" id="m-pos" min="0" max="100" value="${pos}" style="${S.field}">
        </div>
        <div style="${S.toggle}">
          <input type="checkbox" id="m-enabled" ${enabled ? "checked" : ""}>
          <label for="m-enabled">Aktiviert</label>
        </div>
        <div style="${S.actions}">
          <button id="m-cancel" style="${S.btnSec}">Abbrechen</button>
          <button id="m-save"   style="${S.btnPri}">${isEdit ? "Speichern" : "Erstellen"}</button>
        </div>
      </div>
    `;

    // Show/hide fields based on time type
    backdrop.querySelector("#m-timetype").addEventListener("change", e => {
      const sun = e.target.value === "sunrise" || e.target.value === "sunset";
      backdrop.querySelector("#m-time-row").style.display = sun ? "none" : "block";
      backdrop.querySelector("#m-sun-row").style.display  = sun ? "block" : "none";
    });

    // Show/hide position field
    backdrop.querySelector("#m-action").addEventListener("change", e => {
      backdrop.querySelector("#pos-row").style.display =
        e.target.value === "Position" ? "block" : "none";
    });

    backdrop.querySelector("#m-cancel").addEventListener("click", () => {
      backdrop.remove();
    });
    backdrop.addEventListener("click", e => {
      if (e.target === backdrop) backdrop.remove();
    });

    backdrop.querySelector("#m-save").addEventListener("click", () => {
      const typeVal    = backdrop.querySelector("#m-timetype").value;
      const timeVal    = backdrop.querySelector("#m-time").value;
      const offsetVal  = parseInt(backdrop.querySelector("#m-offset").value) || 0;
      const checked    = [...backdrop.querySelectorAll(".m-day-cb:checked")].map(cb => cb.dataset.cron);
      const daySpec    = (checked.length === 0 || checked.length === 7) ? "*" : checked.join(",");
      const actionVal  = backdrop.querySelector("#m-action").value;
      const posVal     = parseInt(backdrop.querySelector("#m-pos").value) || 50;
      const enabledVal = backdrop.querySelector("#m-enabled").checked;
      const deviceName = this._entityToDeviceName(dev.entityId);

      let timespec;
      if (typeVal === "sunrise" || typeVal === "sunset") {
        // Use Shelly's native format: @sunset-0h10m * * <days>
        const absMin  = Math.abs(offsetVal);
        const h       = Math.floor(absMin / 60);
        const m       = absMin % 60;
        const sign   = offsetVal < 0 ? "-" : "+";
        const offStr = offsetVal !== 0 ? `${sign}${h}h${m}m` : "";
        timespec = `@${typeVal}${offStr} * * ${daySpec}`;
      } else {
        const [h, m] = (timeVal || "07:00").split(":").map(Number);
        timespec = `0 ${m} ${h} * * ${daySpec}`;
      }

      let calls;
      if (actionVal === "Einschalten") calls = [{ method: "Switch.Set", params: { id: 0, on: true } }];
      else if (actionVal === "Ausschalten") calls = [{ method: "Switch.Set", params: { id: 0, on: false } }];
      else if (actionVal === "Öffnen") calls = [{ method: "Cover.Open", params: { id: 0 } }];
      else if (actionVal === "Schließen") calls = [{ method: "Cover.Close", params: { id: 0 } }];
      else if (actionVal === "Stoppen") calls = [{ method: "Cover.Stop", params: { id: 0 } }];
      else calls = [{ method: "Cover.GoToPosition", params: { id: 0, pos: posVal } }];

      const data = { device: deviceName, timespec, enable: enabledVal, calls };
      if (isEdit) data.schedule_id = job.id;

      this._callService(isEdit ? "replace_schedule" : "create_schedule", data);
      backdrop.remove();
    });

    // Attach to document body so it overlays everything
    document.body.appendChild(backdrop);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  _getDeviceProfileFromHass(entityId) {
    // Our sensor is not in hass.entities (created via states.async_set),
    // so find the Shelly device by name and check its entities.
    const deviceName = this._hass?.states[entityId]?.attributes?.device_name;
    if (!deviceName || !this._hass?.devices) return "switch";
    const device = Object.values(this._hass.devices).find(d =>
      (d.name_by_user || d.name) === deviceName
    );
    if (!device) return "switch";
    const hasCover = Object.values(this._hass.entities || {})
      .some(e => e.device_id === device.id && e.entity_id.startsWith("cover."));
    return hasCover ? "cover" : "switch";
  }

  _resolveDeviceName(v, entityId) {
    if (!v || v === "") return null;
    if (typeof v === "string") return v;
    const chips = Array.isArray(v) ? v : [v];
    const entityEntry = this._hass?.entities?.[entityId];
    const deviceId = entityEntry?.device_id;
    const areaId = entityEntry?.area_id || this._hass?.devices?.[deviceId]?.area_id;
    const floorId = this._hass?.areas?.[areaId]?.floor_id;
    const parts = chips.map(chip => {
      if (chip.type === "device")   return this._hass?.devices?.[deviceId]?.name_by_user || this._hass?.devices?.[deviceId]?.name;
      if (chip.type === "area")     return this._hass?.areas?.[areaId]?.name;
      if (chip.type === "floor")    return this._hass?.floors?.[floorId]?.name;
      if (chip.type === "label")    return this._hass?.labels?.[chip.label_id]?.name;
      if (chip.type === "entity")   return this._hass?.states?.[entityId]?.attributes?.friendly_name?.replace(" Schedule", "");
      return null;
    }).filter(Boolean);
    return parts.join(" ") || null;
  }

  _entityToDeviceName(entityId) {
    const state = this._hass?.states[entityId];
    // Prefer the exact device_name attribute stored by the integration
    if (state?.attributes?.device_name) return state.attributes.device_name;
    // Fallback: strip "Shelly " prefix and " Schedule" suffix from friendly_name
    if (state?.attributes?.friendly_name) {
      return state.attributes.friendly_name
        .replace(/^Shelly\s+/i, "")
        .replace(/\s*Schedule$/i, "")
        .trim();
    }
    return entityId
      .replace(/^sensor\.shelly_gen1_/, "")
      .replace(/^sensor\.shelly_/, "")
      .replace(/_schedule$/, "")
      .replace(/_/g, " ");
  }

  _callService(service, data = {}) {
    if (!this._hass) return;
    this._hass.callService("shelly_schedule", service, data).catch(err => {
      console.error("shelly_schedule." + service, err);
    });
  }

  // ── Card picker registration ──────────────────────────────────────────────

  static getConfigElement() {
    return document.createElement("shelly-schedule-card-editor");
  }

  static getStubConfig() {
    return { title: "Shelly Schedules", entity: "" };
  }
}

// ── Simple editor element (for card picker "Configuration" tab) ─────────────

class ShellyScheduleCardEditor extends HTMLElement {
  constructor() {
    super();
    this._config = {};
    this._hass = null;
    this._rendered = false;
  }

  setConfig(config) {
    this._config = config || {};
    if (this._rendered) {
      const titleEl      = this.querySelector("#ed-title");
      const hideTitleEl  = this.querySelector("#ed-hide-title");

      const iconEl       = this.querySelector("#ed-icon");
      const colorEl      = this.querySelector("#ed-color");
      if (titleEl)      titleEl.value       = this._config.title       || "";
      if (hideTitleEl)  hideTitleEl.checked  = !!this._config.hide_title;
      const hideWebuiEl = this.querySelector("#ed-hide-webui");
      if (hideWebuiEl)  hideWebuiEl.checked  = this._config.hide_webui !== true;
      const hideActionEl = this.querySelector("#ed-hide-action");
      if (hideActionEl) hideActionEl.checked = this._config.hide_action !== true;
      const badgeModeEl = this.querySelector("#ed-badge-mode");
      if (badgeModeEl) badgeModeEl.value = this._config.badge_mode ?? "id";
      const dayDisplayEl = this.querySelector("#ed-day-display");
      if (dayDisplayEl) dayDisplayEl.value = this._config.day_display ?? "text";
      const nameForm = this.querySelector("#ed-name-form");
      if (nameForm) nameForm.data = { entity: this._config.entity || "", name: this._config.device_name ?? null };
      if (iconEl)       iconEl.value         = this._config.icon        || "";
      const deviceIconEl = this.querySelector("#ed-device-icon");
      if (deviceIconEl) deviceIconEl.value   = this._config.device_icon || "";
      if (colorEl)      colorEl.value        = this._config.color       || "#03a9f4";
      this._updateEntitySelect();
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this._renderEditor();
    } else {
      this._updateEntitySelect();
      const nameForm = this.querySelector("#ed-name-form");
      if (nameForm) nameForm.hass = hass;
    }
  }

  connectedCallback() {
    if (!this._rendered) this._renderEditor();
  }

  _updateEntitySelect() {
    const sel = this.querySelector("#ed-entity");
    if (!sel || !this._hass) return;
    const entities = Object.keys(this._hass.states)
      .filter(eid => eid.startsWith("sensor.shelly") && eid.endsWith("_schedule"))
      .sort();
    const current = this._config.entity || "";
    sel.innerHTML =
      `<option value="">– Entität wählen –</option>` +
      entities.map(eid => {
        const rawName = this._hass.states[eid]?.attributes?.friendly_name || eid;
        const name = rawName.replace(/\bshelly\b\s*/i, "").replace(/\s*schedule$/i, "").trim();
        const entryReg = this._hass.entities?.[eid];
        const areaId = entryReg?.area_id
          || this._hass.devices?.[entryReg?.device_id]?.area_id;
        const area = areaId ? this._hass.areas?.[areaId]?.name : null;
        const label = area ? `${name} · ${area}` : name;
        return `<option value="${eid}" ${eid === current ? "selected" : ""}>${label}</option>`;
      }).join("");
  }

  _fire(config) {
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config }, bubbles: true, composed: true,
    }));
  }

  _renderEditor() {
    const fieldStyle = `
      width: 100%; box-sizing: border-box;
      padding: 10px 12px; border-radius: 6px;
      border: 1px solid var(--divider-color);
      background: var(--card-background-color);
      color: var(--primary-text-color);
      font-size: .95em; font-family: inherit;
    `;

    this.innerHTML = `
      <style>
        .ed-field-label {
          display: block; font-size: .85em;
          color: var(--secondary-text-color); margin-bottom: 4px;
        }
        .ed-row { margin-bottom: 12px; }
        ha-icon-picker { display: block; width: 100%; }
        .ed-section {
          border: 1px solid var(--divider-color);
          border-radius: 8px; margin-top: 12px; overflow: hidden;
        }
        .ed-section-header {
          display: flex; align-items: center; gap: 10px;
          padding: 12px 16px; cursor: pointer;
          background: var(--secondary-background-color);
          user-select: none;
        }
        .ed-section-header:hover { background: var(--primary-background-color); }
        .ed-section-title {
          flex: 1; font-size: .95em; font-weight: 500;
          color: var(--primary-text-color);
        }
        .ed-section-icon { color: var(--secondary-text-color); }
        .ed-chevron {
          color: var(--secondary-text-color);
          transition: transform .2s;
        }
        .ed-chevron.open { transform: rotate(180deg); }
        .ed-section-body { padding: 12px 16px 4px; }
        .ed-section-body.hidden { display: none; }
        .ed-color-row {
          display: flex; align-items: center; gap: 12px; padding: 4px 0 8px;
        }
        .ed-color-row span { font-size: .9em; color: var(--primary-text-color); flex: 1; }
        #ed-color {
          width: 44px; height: 34px; padding: 2px; border-radius: 6px;
          border: 1px solid var(--divider-color); cursor: pointer; background: none;
        }
        .ed-color-clear {
          font-size: .8em; color: var(--secondary-text-color);
          text-decoration: underline; cursor: pointer;
        }
      </style>
      <div style="padding: 0 16px 16px;">

        <div style="font-size:.75em;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--secondary-text-color);padding:16px 0 6px;">Entität</div>
        <div class="ed-row">
          <select id="ed-entity" style="${fieldStyle}"></select>
        </div>

        <div class="ed-section">
          <div class="ed-section-header" data-target="sec-titel">
            <ha-icon class="ed-section-icon" icon="mdi:format-title"></ha-icon>
            <span class="ed-section-title">Titel</span>
            <ha-icon class="ed-chevron open" icon="mdi:chevron-up"></ha-icon>
          </div>
          <div id="sec-titel" class="ed-section-body">
            <div class="ed-row">
              <ha-textfield id="ed-title" label="Kartentitel" placeholder="Shelly Schedules" style="width:100%;"></ha-textfield>
            </div>
            <div class="ed-row" style="display:flex;align-items:center;justify-content:space-between;">
              <label for="ed-hide-title" style="font-size:.9em;color:var(--primary-text-color);cursor:pointer;">Titel ausblenden</label>
              <ha-switch id="ed-hide-title"></ha-switch>
            </div>
            <div class="ed-row">
              <ha-icon-picker id="ed-icon" label="Icon"></ha-icon-picker>
            </div>
            <div class="ed-color-row">
              <span>Akzentfarbe</span>
              <input id="ed-color-titel" type="color" title="Farbe wählen">
              <span class="ed-color-clear" id="ed-color-clear-titel">zurücksetzen</span>
            </div>
          </div>
        </div>

        <div class="ed-section">
          <div class="ed-section-header" data-target="sec-inhalt">
            <ha-icon class="ed-section-icon" icon="mdi:format-list-bulleted"></ha-icon>
            <span class="ed-section-title">Inhalt</span>
            <ha-icon class="ed-chevron open" icon="mdi:chevron-up"></ha-icon>
          </div>
          <div id="sec-inhalt" class="ed-section-body">
            <div class="ed-row">
              <ha-form id="ed-name-form"></ha-form>
            </div>
            <div class="ed-row">
              <ha-icon-picker id="ed-device-icon" label="Icon neben Gerätename"></ha-icon-picker>
            </div>
            <div class="ed-row" style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
              <label style="font-size:.9em;color:var(--primary-text-color);flex:1;">Listenbadge</label>
              <select id="ed-badge-mode" style="font-size:.9em;padding:4px 6px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;">
                <option value="id">ID</option>
                <option value="icon">Aktionssymbol</option>
                <option value="none">Nichts</option>
              </select>
            </div>
            <div class="ed-row" style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
              <label style="font-size:.9em;color:var(--primary-text-color);flex:1;">Tagesanzeige</label>
              <select id="ed-day-display" style="font-size:.9em;padding:4px 6px;border-radius:6px;border:1px solid var(--divider-color);background:var(--card-background-color);color:var(--primary-text-color);cursor:pointer;">
                <option value="text">Text</option>
                <option value="chips">Chips</option>
              </select>
            </div>
            <div class="ed-row" style="display:flex;align-items:center;justify-content:space-between;">
              <label for="ed-hide-webui" style="font-size:.9em;color:var(--primary-text-color);cursor:pointer;">Web-UI Link anzeigen</label>
              <ha-switch id="ed-hide-webui"></ha-switch>
            </div>
            <div class="ed-row" style="display:flex;align-items:center;justify-content:space-between;">
              <label for="ed-hide-action" style="font-size:.9em;color:var(--primary-text-color);cursor:pointer;">Aktion anzeigen</label>
              <ha-switch id="ed-hide-action"></ha-switch>
            </div>
            <div class="ed-row" style="display:flex;align-items:center;justify-content:space-between;">
              <label for="ed-hide-run-button" style="font-size:.9em;color:var(--primary-text-color);cursor:pointer;">Ausführen-Button anzeigen</label>
              <ha-switch id="ed-hide-run-button"></ha-switch>
            </div>
            <div class="ed-color-row">
              <span>Akzentfarbe</span>
              <input id="ed-color" type="color" title="Farbe wählen">
              <span class="ed-color-clear" id="ed-color-clear">zurücksetzen</span>
            </div>
          </div>
        </div>

      </div>
    `;
    this._rendered = true;

    // Collapsible section toggle
    this.querySelectorAll(".ed-section-header").forEach(header => {
      header.addEventListener("click", () => {
        const body    = this.querySelector("#" + header.dataset.target);
        const chevron = header.querySelector(".ed-chevron");
        const open    = !body.classList.contains("hidden");
        body.classList.toggle("hidden", open);
        chevron.classList.toggle("open", !open);
      });
    });

    this._updateEntitySelect();

    // entity select
    const entitySelect = this.querySelector("#ed-entity");
    entitySelect.addEventListener("change", e => {
      this._config = { ...this._config, entity: e.target.value };
      if (nameForm) nameForm.data = { entity: e.target.value, name: this._config.device_name ?? null };
      this._fire(this._config);
    });

    // title
    const titleEl = this.querySelector("#ed-title");
    titleEl.value = this._config.title || "";
    titleEl.addEventListener("change", e => {
      this._config = { ...this._config, title: e.target.value };
      this._fire(this._config);
    });

    // hide title
    const hideTitleEl = this.querySelector("#ed-hide-title");
    hideTitleEl.checked = !!this._config.hide_title;
    hideTitleEl.addEventListener("change", e => {
      this._config = { ...this._config, hide_title: e.target.checked };
      this._fire(this._config);
    });

    // badge mode
    const badgeModeEl = this.querySelector("#ed-badge-mode");
    badgeModeEl.value = this._config.badge_mode ?? "id";
    badgeModeEl.addEventListener("change", e => {
      this._config = { ...this._config, badge_mode: e.target.value };
      this._fire(this._config);
    });

    // day display
    const dayDisplayEl = this.querySelector("#ed-day-display");
    dayDisplayEl.value = this._config.day_display ?? "text";
    dayDisplayEl.addEventListener("change", e => {
      this._config = { ...this._config, day_display: e.target.value };
      this._fire(this._config);
    });

    // hide web-ui (default: shown = switch ON)
    const hideWebuiEl = this.querySelector("#ed-hide-webui");
    hideWebuiEl.checked = this._config.hide_webui !== true;
    hideWebuiEl.addEventListener("change", e => {
      this._config = { ...this._config, hide_webui: !e.target.checked };
      this._fire(this._config);
    });

    // hide action text (default: shown = switch ON)
    const hideActionEl = this.querySelector("#ed-hide-action");
    hideActionEl.checked = this._config.hide_action !== true;
    hideActionEl.addEventListener("change", e => {
      this._config = { ...this._config, hide_action: !e.target.checked };
      this._fire(this._config);
    });

    // hide run button (default: shown = switch ON)
    const hideRunBtnEl = this.querySelector("#ed-hide-run-button");
    hideRunBtnEl.checked = this._config.hide_run_button !== true;
    hideRunBtnEl.addEventListener("change", e => {
      this._config = { ...this._config, hide_run_button: !e.target.checked };
      this._fire(this._config);
    });

    // device name — ha-form with entity_name selector
    // context: { entity: "entity" } tells ha-form to resolve data["entity"] as the entity context
    const nameForm = this.querySelector("#ed-name-form");
    const _applyNameForm = () => {
      nameForm.hass         = this._hass;
      nameForm.schema       = [{ name: "name", selector: { entity_name: {} }, context: { entity: "entity" } }];
      nameForm.data         = { entity: this._config.entity || "", name: this._config.device_name ?? null };
      nameForm.computeLabel = () => "Name";
    };
    customElements.whenDefined("ha-form").then(_applyNameForm);
    nameForm.addEventListener("value-changed", e => {
      const v = e.detail.value?.name ?? null;
      const { device_name, ...rest } = this._config;
      const isEmpty = !v || v === "" || (Array.isArray(v) && v.length === 0);
      // store raw value so picker restores chip state on reopen
      this._config = !isEmpty ? { ...rest, device_name: v } : rest;
      this._fire(this._config);
    });

    // icon picker
    const iconEl = this.querySelector("#ed-icon");
    iconEl.value = this._config.icon || "";
    iconEl.addEventListener("value-changed", e => {
      this._config = { ...this._config, icon: e.detail.value };
      this._fire(this._config);
    });

    // device icon (shown next to device name in card)
    const deviceIconEl = this.querySelector("#ed-device-icon");
    deviceIconEl.value = this._config.device_icon || "";
    deviceIconEl.addEventListener("value-changed", e => {
      const { device_icon, ...rest } = this._config;
      const v = e.detail.value;
      this._config = v ? { ...rest, device_icon: v } : rest;
      this._fire(this._config);
    });

    // color (Inhalt + Titel — beide steuern denselben config-Wert)
    const colorEl      = this.querySelector("#ed-color");
    const colorTitelEl = this.querySelector("#ed-color-titel");
    const syncColor = (val, opacity) => {
      colorEl.value      = val;
      colorEl.style.opacity = opacity;
      colorTitelEl.value = val;
      colorTitelEl.style.opacity = opacity;
    };
    syncColor(this._config.color || "#03a9f4", this._config.color ? "1" : "0.45");

    const onColorInput = e => {
      syncColor(e.target.value, "1");
      this._config = { ...this._config, color: e.target.value };
      this._fire(this._config);
    };
    colorEl.addEventListener("input", onColorInput);
    colorTitelEl.addEventListener("input", onColorInput);

    const onColorClear = () => {
      syncColor("#03a9f4", "0.45");
      const { color, ...rest } = this._config;
      this._config = rest;
      this._fire(this._config);
    };
    this.querySelector("#ed-color-clear").addEventListener("click", onColorClear);
    this.querySelector("#ed-color-clear-titel").addEventListener("click", onColorClear);
  }
}

customElements.define("shelly-schedule-card-editor", ShellyScheduleCardEditor);
customElements.define("shelly-schedule-card", ShellyScheduleCard);

// Register in HA card picker
window.customCards = window.customCards || [];
window.customCards.push({
  type: "shelly-schedule-card",
  name: "Shelly Schedule",
  description: "Manage Shelly device schedules (Gen1, Gen2, Gen3)",
  preview: false,
  documentationURL: "https://github.com/DawidSu/hass-shelly-schedule",
});
