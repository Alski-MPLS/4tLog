'use strict';

let refreshTimer = null;

function escHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function renderCard(d) {
  const statusClass = `status-${d.status || 'gray'}`;

  const diskRow = d.disk_used && d.disk_used !== 'n/a'
    ? `<div class="card-row"><span class="card-row-label">Disk</span><span class="card-row-value">${escHtml(d.disk_used)}</span></div>`
    : '';

  let cpuMemRow;
  if (d.snmp_status && d.snmp_status !== 'ok') {
    const label = d.snmp_status === 'timeout' ? 'SNMP timeout'
      : d.snmp_status === 'disabled' ? 'SNMP disabled'
      : 'SNMP unreachable';
    cpuMemRow = `<div class="card-row"><span class="card-row-label">CPU / Mem</span><span class="card-row-value text-muted">${escHtml(label)}</span></div>`;
  } else if (d.cpu !== null && d.cpu !== undefined && d.mem !== null && d.mem !== undefined) {
    cpuMemRow = `<div class="card-row"><span class="card-row-label">CPU / Mem</span><span class="card-row-value">${d.cpu}% / ${d.mem}%</span></div>`;
  } else {
    cpuMemRow = '';
  }

  const errorRow = d.error
    ? `<div class="card-row card-row-error"><span class="card-row-value text-danger">${escHtml(d.error)}</span></div>`
    : '';

  return `
<div class="infra-card ${statusClass}">
  <div class="infra-card-stripe"></div>
  <div class="infra-card-body">
    <div class="card-name-block">
      <div class="card-title">${escHtml(d.label)}</div>
      <div class="card-subtitle">${escHtml(d.host)} &bull; ADOM ${escHtml(d.adom)}</div>
    </div>
    <div class="card-detail-block">
      <div class="card-col card-col-hostname">
        <div class="card-row"><span class="card-row-label">Hostname</span><span class="card-row-value">${escHtml(d.hostname)}</span></div>
      </div>
      <div class="card-col card-col-meta">
        <div class="card-row"><span class="card-row-label">Version</span><span class="card-row-value">${escHtml(d.version)}</span></div>
        <div class="card-row"><span class="card-row-label">Serial</span><span class="card-row-value">${escHtml(d.serial)}</span></div>
        <div class="card-row"><span class="card-row-label">HA Mode / Role</span><span class="card-row-value">${escHtml(d.ha_mode)} / ${escHtml(d.ha_role)}</span></div>
        ${cpuMemRow}
        ${diskRow}
      </div>
      ${errorRow}
    </div>
  </div>
</div>`;
}

async function loadDashboard() {
  const grid = document.getElementById('dashboardGrid');
  try {
    const resp = await fetch('/api/dashboard');
    if (resp.status === 401) { location.href = '/login'; return; }
    const data = await resp.json();
    if (!Array.isArray(data)) {
      grid.innerHTML = `<div class="alert alert-danger">Error: ${escHtml(JSON.stringify(data))}</div>`;
      return;
    }
    if (data.length === 0) {
      grid.innerHTML = '<div class="loading-placeholder">No FortiAnalyzer targets configured. Add one under Admin &rarr; FAZ Targets.</div>';
      return;
    }
    grid.innerHTML = data.map(renderCard).join('');
    document.getElementById('lastUpdated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (err) {
    grid.innerHTML = `<div class="alert alert-danger">Failed to load: ${escHtml(err.message)}</div>`;
  }
}

function scheduleRefresh(seconds) {
  clearInterval(refreshTimer);
  if (seconds > 0) refreshTimer = setInterval(loadDashboard, seconds * 1000);
}

document.getElementById('refreshBtn').addEventListener('click', loadDashboard);
document.getElementById('autoRefresh').addEventListener('change', function () {
  scheduleRefresh(parseInt(this.value, 10));
});

loadDashboard();
scheduleRefresh(parseInt(document.getElementById('autoRefresh').value, 10));
