'use strict';

(function () {

const SECTIONS = [
  {
    id: 'overview',
    label: 'Overview',
    html: `
<h3>What is 4tlog?</h3>
<p>4tlog is a read-only tool for monitoring and searching FortiAnalyzer appliances — no configuration changes are ever made to any device.</p>
<h3>Navigation</h3>
<ul>
  <li><strong>Dashboard</strong> — live health cards (status, version, serial, disk, CPU/mem) for each configured FortiAnalyzer appliance.</li>
  <li><strong>Log Search</strong> — targeted traffic-log search by source/destination IP, port/service, time range, and advanced fields, with CSV/JSON export.</li>
  <li><strong>Admin</strong> — manage users, groups/tab permissions, FAZ targets, and view system logs (admins only).</li>
</ul>
`,
  },
  {
    id: 'dashboard',
    label: 'Dashboard',
    tab: 'dashboard',
    html: `
<h3>Health cards</h3>
<p>Each card shows a FortiAnalyzer appliance's connectivity status, hostname, version, serial, disk usage, and (if SNMP is enabled) CPU/memory gauges. Data refreshes on a background timer — the page never blocks waiting on a live device call.</p>
<h3>Status colors</h3>
<div class="help-status-list">
  <span class="status-dot green"></span> <span><strong>Green</strong> — reachable, metrics within normal range (or SNMP disabled).</span>
  <span class="status-dot yellow"></span> <span><strong>Yellow</strong> — CPU or memory elevated (warn threshold).</span>
  <span class="status-dot red"></span> <span><strong>Red</strong> — CPU or memory critical.</span>
  <span class="status-dot gray"></span> <span><strong>Gray</strong> — first poll still pending.</span>
</div>
<p>An "offline" card with a red error message means the last poll failed — check the message for whether it's a connection issue or a permission error on the FortiAnalyzer side.</p>
`,
  },
  {
    id: 'log_search',
    label: 'Log Search',
    tab: 'log_search',
    html: `
<h3>Required filters</h3>
<p>At least one of Source IP or Destination IP must be filled in — searches with both left blank (ANY/ANY) are blocked to keep queries targeted and fast.</p>
<h3>IP formats</h3>
<p>Each IP box accepts a comma-separated list of single IPs, CIDR blocks (<code>10.1.1.0/24</code>), or explicit ranges (<code>10.1.1.1-10.1.1.10</code>) — IPv4 or IPv6.</p>
<h3>Port/Service formats</h3>
<p>Accepts a port number (<code>443</code>), <code>tcp:443</code>/<code>udp:53</code>, a range (<code>tcp:1000-1200</code>), or a bare service name (<code>HTTPS</code>). Leave blank to match any port/service.</p>
<h3>Advanced filters</h3>
<p>Use "+ Add filter" to add extra field/operator/value rows beyond the basics — narrows the search further.</p>
<h3>Export</h3>
<p>"Export CSV"/"Export JSON" download exactly the rows currently shown in the results table.</p>
`,
  },
  {
    id: 'admin',
    label: 'Admin',
    adminOnly: true,
    html: `
<h3>Groups &amp; tab permissions</h3>
<p>Groups control which tabs a user can see (<strong>allowed_tabs</strong>) and, optionally, which FortiAnalyzer targets/ADOMs they can view on the Dashboard and Log Search (<strong>adom_restrict</strong> + <strong>allowed_adoms</strong>).</p>
<h3>FAZ Targets</h3>
<p>Each target is one FortiAnalyzer appliance/ADOM: label, host, ADOM, bearer token, and optional per-target SNMP credential overrides. Edits take effect on the next poll cycle without an app restart.</p>
<h3>Logs</h3>
<p>The Logs sub-tab shows the app's own in-memory log buffer — useful for diagnosing a failed poll or search without shell access to the container.</p>
`,
  },
];

const allowed = new Set(window._helpAllowedTabs || []);
const isAdmin = Boolean(window._helpIsAdmin);

function visibleSections() {
  return SECTIONS.filter((s) => {
    if (s.adminOnly) return isAdmin;
    if (s.tab) return allowed.has(s.tab);
    return true;
  });
}

function buildPanel() {
  const sections = visibleSections();
  if (!sections.length) return;

  const tabBtns = sections.map((s, i) =>
    `<button class="help-tab${i === 0 ? ' active' : ''}" data-tab="${s.id}">${s.label}</button>`
  ).join('');
  const tabPanes = sections.map((s, i) =>
    `<div class="help-pane${i === 0 ? ' active' : ''}" id="help-pane-${s.id}">${s.html}</div>`
  ).join('');

  const panel = document.createElement('div');
  panel.id = 'helpPanel';
  panel.className = 'help-panel hidden';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', 'Help');
  panel.innerHTML = `
<div class="help-panel-inner">
  <div class="help-header">
    <span class="help-title">&#10067; Help &amp; Guide</span>
    <button class="help-close" id="helpClose" aria-label="Close help">&times;</button>
  </div>
  <div class="help-tabs">${tabBtns}</div>
  <div class="help-body">${tabPanes}</div>
</div>`;
  document.body.appendChild(panel);

  const backdrop = document.createElement('div');
  backdrop.id = 'helpBackdrop';
  backdrop.className = 'help-backdrop hidden';
  document.body.appendChild(backdrop);
}

function wirePanel() {
  const panel = document.getElementById('helpPanel');
  const backdrop = document.getElementById('helpBackdrop');
  const btn = document.getElementById('helpBtn');
  if (!panel) return;

  function open() {
    panel.classList.remove('hidden');
    backdrop.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    panel.classList.add('hidden');
    backdrop.classList.add('hidden');
    document.body.style.overflow = '';
  }

  btn.addEventListener('click', open);
  document.getElementById('helpClose').addEventListener('click', close);
  backdrop.addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

  panel.querySelectorAll('.help-tab').forEach((tab) => {
    tab.addEventListener('click', function () {
      panel.querySelectorAll('.help-tab').forEach((t) => t.classList.remove('active'));
      panel.querySelectorAll('.help-pane').forEach((p) => p.classList.remove('active'));
      this.classList.add('active');
      document.getElementById(`help-pane-${this.dataset.tab}`).classList.add('active');
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  if (!document.getElementById('helpBtn')) return;
  buildPanel();
  wirePanel();
});

})();
