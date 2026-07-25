'use strict';

let currentRows = [];
let currentFields = [];

function escHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toFazTime(date) {
  // Send an unambiguous UTC instant — the backend (FAZClient.local_time_range)
  // converts this to the target appliance's own configured timezone before
  // submitting the search, since FortiAnalyzer interprets time-range.start/end
  // in its own local time, not UTC and not the browser's local time (a naive
  // browser-local timestamp broke as soon as the browser and the appliance
  // were in different timezones — confirmed live).
  return date.toISOString();
}

function presetToRange(preset) {
  const end = new Date();
  const start = new Date(end);
  const match = preset.match(/^(\d+)([mhd])$/);
  if (!match) return null;
  const amount = parseInt(match[1], 10);
  if (match[2] === 'm') start.setMinutes(start.getMinutes() - amount);
  if (match[2] === 'h') start.setHours(start.getHours() - amount);
  if (match[2] === 'd') start.setDate(start.getDate() - amount);
  return { start: toFazTime(start), end: toFazTime(end) };
}

async function loadTargets() {
  const select = document.getElementById('targetSelect');
  try {
    const resp = await fetch('/api/log-search/targets');
    if (resp.status === 401) { location.href = '/login'; return; }
    const targets = await resp.json();
    if (!Array.isArray(targets)) {
      select.innerHTML = '<option value="">(unable to load targets)</option>';
      return;
    }
    select.innerHTML = targets.map((t) => `<option value="${escHtml(t.label)}">${escHtml(t.label)} (${escHtml(t.host)})</option>`).join('');
    await loadDevices();
  } catch {
    select.innerHTML = '<option value="">(unable to load targets)</option>';
  }
}

async function loadDevices() {
  const deviceSelect = document.getElementById('deviceInput');
  const target = document.getElementById('targetSelect').value;
  const allOption = '<option value="All_FortiGate" selected>All_FortiGate</option>';
  if (!target) {
    deviceSelect.innerHTML = allOption;
    return;
  }
  try {
    const resp = await fetch(`/api/log-search/devices?target=${encodeURIComponent(target)}`);
    if (!resp.ok) { deviceSelect.innerHTML = allOption; return; }
    const devices = await resp.json();
    if (!Array.isArray(devices) || devices.length === 0) {
      deviceSelect.innerHTML = allOption;
      return;
    }
    deviceSelect.innerHTML = allOption + devices.map((d) =>
      `<option value="${escHtml(d.devid)}">${escHtml(d.name || d.devid)}${d.platform ? ' (' + escHtml(d.platform) + ')' : ''}</option>`
    ).join('');
  } catch {
    deviceSelect.innerHTML = allOption;
  }
}

function addFilterRow() {
  const container = document.getElementById('extraFilters');
  const row = document.createElement('div');
  row.className = 'extra-filter-row';
  row.innerHTML = `
    <input type="text" class="form-control filter-field" placeholder="field (e.g. action)" />
    <select class="form-select filter-op">
      <option value="==">==</option>
      <option value="!=">!=</option>
    </select>
    <input type="text" class="form-control filter-value" placeholder="value" />
    <button type="button" class="btn btn-sm btn-secondary remove-filter-btn">Remove</button>
  `;
  row.querySelector('.remove-filter-btn').addEventListener('click', () => row.remove());
  container.appendChild(row);
}

function collectExtraFilters() {
  return Array.from(document.querySelectorAll('#extraFilters .extra-filter-row')).map((row) => ({
    field: row.querySelector('.filter-field').value.trim(),
    op: row.querySelector('.filter-op').value,
    value: row.querySelector('.filter-value').value.trim(),
  })).filter((f) => f.field && f.value);
}

function renderResults(result) {
  currentRows = result.rows;
  currentFields = result.fields;
  const headerRow = document.getElementById('resultsHeaderRow');
  const body = document.getElementById('resultsBody');
  headerRow.innerHTML = currentFields.map((f) => `<th>${escHtml(f)}</th>`).join('');
  body.innerHTML = currentRows.map((row) =>
    `<tr>${currentFields.map((f) => `<td>${escHtml(row[f])}</td>`).join('')}</tr>`
  ).join('');
  document.getElementById('truncatedBanner').classList.toggle('hidden', !result.truncated);
  document.getElementById('exportCsvBtn').disabled = currentRows.length === 0;
  document.getElementById('exportJsonBtn').disabled = currentRows.length === 0;
}

function downloadBlob(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function exportCsv() {
  const header = currentFields.join(',');
  const lines = currentRows.map((row) =>
    currentFields.map((f) => `"${String(row[f] ?? '').replace(/"/g, '""')}"`).join(',')
  );
  downloadBlob([header, ...lines].join('\n'), 'log_search_results.csv', 'text/csv');
}

function exportJson() {
  downloadBlob(JSON.stringify(currentRows, null, 2), 'log_search_results.json', 'application/json');
}

async function runSearch(e) {
  e.preventDefault();
  const errBox = document.getElementById('searchError');
  errBox.classList.add('hidden');

  const preset = document.getElementById('timePreset').value;
  let start_time, end_time;
  if (preset === 'custom') {
    // <input type="datetime-local"> values represent browser-local time
    // with no timezone/seconds (e.g. "2026-07-25T14:30"). Run them through
    // the same Date -> toFazTime() conversion presets use so both paths
    // consistently send a UTC-based timestamp with seconds — otherwise
    // preset and custom searches silently target different time windows
    // on any FortiAnalyzer appliance not running in UTC.
    const startValue = document.getElementById('startTime').value;
    const endValue = document.getElementById('endTime').value;
    start_time = startValue ? toFazTime(new Date(startValue)) : '';
    end_time = endValue ? toFazTime(new Date(endValue)) : '';
  } else {
    const range = presetToRange(preset);
    start_time = range.start;
    end_time = range.end;
  }

  const payload = {
    target: document.getElementById('targetSelect').value,
    logtype: document.getElementById('logtypeSelect').value,
    device: document.getElementById('deviceInput').value,
    start_time,
    end_time,
    source_ips: document.getElementById('sourceIps').value,
    destination_ips: document.getElementById('destIps').value,
    ports: document.getElementById('ports').value,
    extra_filters: collectExtraFilters(),
  };

  const searchBtn = document.getElementById('searchBtn');
  searchBtn.disabled = true;
  searchBtn.textContent = 'Searching…';
  try {
    const resp = await fetch('/api/log-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    let body;
    try {
      body = await resp.json();
    } catch {
      errBox.textContent = 'Search failed — please try again.';
      errBox.classList.remove('hidden');
      return;
    }
    if (!resp.ok) {
      errBox.textContent = body.error || 'Search failed.';
      errBox.classList.remove('hidden');
      return;
    }
    renderResults(body);
  } catch {
    errBox.textContent = 'Search failed — please try again.';
    errBox.classList.remove('hidden');
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';
  }
}

document.getElementById('timePreset').addEventListener('change', function () {
  document.getElementById('customTimeRow').classList.toggle('hidden', this.value !== 'custom');
});
document.getElementById('targetSelect').addEventListener('change', loadDevices);
document.getElementById('addFilterBtn').addEventListener('click', addFilterRow);
document.getElementById('searchForm').addEventListener('submit', runSearch);
document.getElementById('exportCsvBtn').addEventListener('click', exportCsv);
document.getElementById('exportJsonBtn').addEventListener('click', exportJson);

loadTargets();
