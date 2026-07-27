# Log Search Columns, Refine Filter & Column Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Log Search a fixed, sensible column order for its 6 most important fields, a client-side refine filter (simple/regex, with negate) over already-fetched results, and a persistent column-visibility picker for everything else.

**Architecture:** All changes are client-side, in `app/static/js/log_search.js` (logic) and `app/templates/log_search.html` (markup) plus `app/static/css/style.css` (styling for the new filter row and columns popover). No backend/API changes — `POST /api/log-search` already returns the full row/field set; everything here operates on that response in the browser. State flows: `currentRows` (raw fetch, unchanged) → `visibleRows` (after refine filter) → `renderPage()` (after column order + column visibility) → pagination/export (read `visibleRows`, not `currentRows`).

**Tech Stack:** Vanilla JS (no framework, no bundler, no JS test runner in this repo — verification is manual in-browser per the existing pattern in this file), Flask/Jinja templates, hand-written CSS.

## Global Constraints

- No backend or API changes — this plan is 100% client-side (spec: "Scope").
- The 6 pinned virtual columns (Date/Time, Source, Destination, Port, Action, Firewall) always render, in that order, and can never be hidden via the column-visibility picker (spec §1, §3).
- A virtual/pinned column is included only if at least one of its source raw fields exists anywhere in the current result set — same omit-if-absent behavior the current `PINNED_FIELDS.filter(...)` has (spec §1).
- Raw fields consumed by a virtual column must not also appear as their own separate raw column (spec §1).
- Refine filter must not mutate `currentRows`; it produces a derived list that pagination, the results-summary count, and CSV/JSON export all read from (spec §2).
- Hidden-column state is a flat list of raw field names in `localStorage` key `logSearchHiddenColumns`, applied globally (not scoped per log type) (spec §3).
- Hiding a column must not remove its value from the refine filter's row-text match — only rendering is affected (spec "Interaction between the three features").
- No new pytest coverage (no backend changes). Verify manually in-browser per spec's Testing section.

---

### Task 1: Virtual column definitions and field ordering, wired into rendering and export

**Files:**
- Modify: `app/static/js/log_search.js:1-18` (replace `PINNED_FIELDS`/`FIELD_LABELS`/`orderFields`)
- Modify: `app/static/js/log_search.js` (`renderPage`, `renderResults`, `exportCsv`) — done in the same task as the constant replacement above, not split out, because `renderPage`/`renderResults` reference `FIELD_LABELS`/`currentFields` directly: removing those constants without also updating their call sites in the same task would leave the page throwing a `ReferenceError` on load and unable to render anything, making the task un-testable on its own.

**Interfaces:**
- Consumes: nothing new (pure refactor of existing module-level state).
- Produces:
  - `VIRTUAL_COLUMNS`: ordered array of column definitions, each `{ key, label, sourceFields, render }` where `key` is a stable string id (e.g. `'datetime'`, `'source'`, `'destination'`, `'port'`, `'action'`, `'firewall'`), `sourceFields` is an array of raw field names consumed (in priority order for that column), and `render(row)` returns the display string for that column given a raw row object.
  - `buildColumns(fields)` — replaces `orderFields(fields)`. Takes the raw field-name array from a search response and returns an array of column descriptors to render, each `{ key, label, isVirtual, raw }` where `raw` is the raw field name (only set for non-virtual columns; used by later tasks for the visibility picker and cell lookups). Virtual columns appear first (in `VIRTUAL_COLUMNS` order, skipping any whose `sourceFields` are all absent from `fields`), followed by remaining unconsumed raw fields in their existing (alphabetical) order.
  - `cellValue(column, row)` — given a column descriptor from `buildColumns()` and a raw row, returns the display string (calls `column.render(row)` for virtual columns, `escHtml`-safe raw lookup for plain columns — `escHtml` is applied by the caller, same as today).

- [ ] **Step 1: Replace the pinned-fields constants and `orderFields` with virtual column definitions**

Replace lines 8–18 of `app/static/js/log_search.js`:

```javascript
// The 6 columns below are always shown first, in this order, when their
// underlying raw field(s) exist in the result set — the rest of the
// returned fields follow in their existing (alphabetical) order. Each
// virtual column merges one or more raw FortiAnalyzer fields into a single
// display value (e.g. Source = srcip, plus a resolved name if the row has
// one). Field-name fallbacks here are defensive: confirmed live traffic
// logs only return srcip/dstip, no resolved name field, so srcname/srchost
// are untested guesses for logs that do resolve names.
const VIRTUAL_COLUMNS = [
  {
    key: 'datetime',
    label: 'Date/Time',
    sourceFields: ['date', 'time', 'itime', 'eventtime'],
    render(row) {
      if (row.date != null && row.time != null) return `${row.date} ${row.time}`;
      for (const f of ['itime', 'eventtime', 'date']) {
        if (row[f] != null) return String(row[f]);
      }
      return '';
    },
  },
  {
    key: 'source',
    label: 'Source',
    sourceFields: ['srcip', 'srcname', 'srchost'],
    render(row) {
      const name = row.srcname || row.srchost;
      if (name && row.srcip) return `${name} (${row.srcip})`;
      return name || row.srcip || '';
    },
  },
  {
    key: 'destination',
    label: 'Destination',
    sourceFields: ['dstip', 'dstname', 'dsthost'],
    render(row) {
      const name = row.dstname || row.dsthost;
      if (name && row.dstip) return `${name} (${row.dstip})`;
      return name || row.dstip || '';
    },
  },
  {
    key: 'port',
    label: 'Port',
    sourceFields: ['dstport', 'service'],
    render(row) {
      if (row.dstport != null && row.service) return `${row.dstport}/${row.service}`;
      if (row.dstport != null) return String(row.dstport);
      return row.service || '';
    },
  },
  {
    key: 'action',
    label: 'Action',
    sourceFields: ['action'],
    render(row) { return row.action != null ? String(row.action) : ''; },
  },
  {
    key: 'firewall',
    label: 'Firewall',
    sourceFields: ['devname', 'devid'],
    render(row) { return row.devname || row.devid || ''; },
  },
];

function buildColumns(fields) {
  const fieldSet = new Set(fields);
  const consumed = new Set();
  const columns = [];
  for (const vc of VIRTUAL_COLUMNS) {
    const present = vc.sourceFields.filter((f) => fieldSet.has(f));
    if (present.length === 0) continue;
    present.forEach((f) => consumed.add(f));
    columns.push({ key: vc.key, label: vc.label, isVirtual: true, render: vc.render });
  }
  const rest = fields.filter((f) => !consumed.has(f));
  for (const f of rest) {
    columns.push({ key: f, label: f, isVirtual: false, raw: f });
  }
  return columns;
}

function cellValue(column, row) {
  return column.isVirtual ? column.render(row) : row[column.raw];
}
```

- [ ] **Step 2: Replace `currentFields` usages in render/export with column-aware versions**

Add a new module-level variable near the top (with the other `let currentRows = [];` etc.):

```javascript
let currentColumns = [];
```

Update `renderResults` (currently `currentFields = orderFields(result.fields);`) to:

```javascript
function renderResults(result) {
  currentRows = result.rows;
  currentFields = result.fields;
  currentColumns = buildColumns(currentFields);
  currentPage = 1;
  renderPage();
  document.getElementById('truncatedBanner').classList.toggle('hidden', !result.truncated);
  document.getElementById('exportCsvBtn').disabled = currentRows.length === 0;
  document.getElementById('exportJsonBtn').disabled = currentRows.length === 0;
}
```

Update `renderPage`'s header/body rendering (currently using `currentFields` + `FIELD_LABELS`) to use `currentColumns` + `cellValue`:

```javascript
function renderPage() {
  const headerRow = document.getElementById('resultsHeaderRow');
  const body = document.getElementById('resultsBody');
  headerRow.innerHTML = currentColumns.map((c) => `<th>${escHtml(c.label)}</th>`).join('');

  const start = (currentPage - 1) * pageSize;
  const pageRows = currentRows.slice(start, start + pageSize);
  body.innerHTML = pageRows.map((row) =>
    `<tr>${currentColumns.map((c) => `<td>${escHtml(cellValue(c, row))}</td>`).join('')}</tr>`
  ).join('');

  const total = currentRows.length;
  const pages = totalPages();
  document.getElementById('resultsSummary').textContent = total === 0
    ? 'No results'
    : `Showing ${start + 1}–${Math.min(start + pageSize, total)} of ${total}`;
  document.getElementById('pageIndicator').textContent = `Page ${currentPage} of ${pages}`;
  document.getElementById('firstPageBtn').disabled = currentPage <= 1;
  document.getElementById('prevPageBtn').disabled = currentPage <= 1;
  document.getElementById('nextPageBtn').disabled = currentPage >= pages;
  document.getElementById('lastPageBtn').disabled = currentPage >= pages;
}
```

Update `exportCsv`/`exportJson` to use `currentColumns`/`cellValue` for CSV (JSON export stays row-based — it exports raw row objects, which is unaffected by column ordering):

```javascript
function exportCsv() {
  const header = currentColumns.map((c) => c.label).join(',');
  const lines = currentRows.map((row) =>
    currentColumns.map((c) => `"${String(cellValue(c, row) ?? '').replace(/"/g, '""')}"`).join(',')
  );
  downloadBlob([header, ...lines].join('\n'), 'log_search_results.csv', 'text/csv');
}
```

`exportJson` is unchanged for this task (it exports `currentRows` directly — Task 2 will change both exports to read from the filtered row list instead of `currentRows`).

This replaces every remaining reference to the old `PINNED_FIELDS`/`FIELD_LABELS`/`orderFields` names, so after this step none of those three identifiers appear anywhere in the file.

- [ ] **Step 3: Manually verify in-browser (traffic log)**

Run `uv run python wsgi.py`, log in, open Log Search, run a traffic-log search with a known source/dest IP. Confirm:
- The page loads with no console errors.
- The results table header shows "Date/Time, Source, Destination, Port, Action, Firewall" (for whichever are present) followed by any extra fields — note whichever fields your appliance actually returns for Date/Time (`date`+`time`, or one of `itime`/`eventtime`), since this is a defensive fallback that hasn't been confirmed live.
- Cell values render correctly (Source shows the raw IP since no name-resolution fields exist yet, per the spec's confirmed-live note).
- Click "Export CSV" and open the downloaded file — header row matches the on-screen column order/labels.

- [ ] **Step 4: Commit**

```bash
git add app/static/js/log_search.js
git commit -m "log-search: fixed 6-column virtual ordering for table render and CSV export"
```

---

### Task 2: Refine filter (simple/regex, negate, live)

**Files:**
- Modify: `app/templates/log_search.html` (add filter row markup above the results table)
- Modify: `app/static/js/log_search.js` (filter state + `visibleRows` derivation)
- Modify: `app/static/css/style.css` (style the new filter row)

**Interfaces:**
- Consumes: `currentRows`, `currentColumns`, `cellValue` from Task 1.
- Produces:
  - `visibleRows` (module-level array): the filtered row list. `renderPage`, `totalPages`, `goToPage`, `exportCsv`, and `exportJson` are updated to read `visibleRows` instead of `currentRows`.
  - `applyRefineFilter()`: recomputes `visibleRows` from `currentRows` based on the current filter term/mode/negate state, resets `currentPage` to 1, calls `renderPage()`.

- [ ] **Step 1: Add the filter row markup**

In `app/templates/log_search.html`, insert directly above the `<div id="truncatedBanner" ...>` block (after the closing `</form>` tag, i.e. after line 76):

```html
<div class="refine-filter-row">
  <input type="text" id="refineFilterInput" class="form-control" placeholder="Filter results (e.g. 8.8.8.8)" />
  <select id="refineFilterMode" class="form-select-sm">
    <option value="contains" selected>Contains</option>
    <option value="regex">Regex</option>
  </select>
  <label class="refine-negate-label">
    <input type="checkbox" id="refineFilterNegate" /> Negate
  </label>
  <span id="refineFilterError" class="refine-filter-error hidden"></span>
</div>
```

- [ ] **Step 2: Add filter styling**

In `app/static/css/style.css`, add after the `.table-controls-right { ... }` rule (around line 439):

```css
.refine-filter-row {
  display: flex;
  align-items: center;
  gap: .5rem;
  margin-bottom: .5rem;
}
.refine-filter-row #refineFilterInput { max-width: 320px; }
.refine-negate-label {
  display: flex;
  align-items: center;
  gap: .3rem;
  font-size: .85rem;
  white-space: nowrap;
}
.refine-filter-error {
  font-size: .8rem;
  color: var(--danger, #dc3545);
}
```

- [ ] **Step 3: Add `visibleRows` state and `applyRefineFilter()`, switch render/export/pagination to read it**

In `app/static/js/log_search.js`, add near the other module-level `let` declarations:

```javascript
let visibleRows = [];
```

Add the filter function (place it after `cellValue`, before `totalPages`):

```javascript
function rowMatches(row, term, mode) {
  const haystack = currentColumns.map((c) => String(cellValue(c, row) ?? '')).join(' ␟ ');
  if (mode === 'regex') {
    return new RegExp(term, 'i').test(haystack);
  }
  return haystack.toLowerCase().includes(term.toLowerCase());
}

function applyRefineFilter() {
  const term = document.getElementById('refineFilterInput').value.trim();
  const mode = document.getElementById('refineFilterMode').value;
  const negate = document.getElementById('refineFilterNegate').checked;
  const errBox = document.getElementById('refineFilterError');
  errBox.classList.add('hidden');

  if (!term) {
    visibleRows = currentRows;
    currentPage = 1;
    renderPage();
    return;
  }

  try {
    visibleRows = currentRows.filter((row) => {
      const matched = rowMatches(row, term, mode);
      return negate ? !matched : matched;
    });
  } catch (exc) {
    errBox.textContent = mode === 'regex' ? `Invalid regex: ${exc.message}` : 'Filter error';
    errBox.classList.remove('hidden');
    return;
  }
  currentPage = 1;
  renderPage();
}
```

Update `renderResults` to initialize `visibleRows` alongside `currentRows`:

```javascript
function renderResults(result) {
  currentRows = result.rows;
  currentFields = result.fields;
  currentColumns = buildColumns(currentFields);
  visibleRows = currentRows;
  document.getElementById('refineFilterInput').value = '';
  document.getElementById('refineFilterNegate').checked = false;
  document.getElementById('refineFilterError').classList.add('hidden');
  currentPage = 1;
  renderPage();
  document.getElementById('truncatedBanner').classList.toggle('hidden', !result.truncated);
  document.getElementById('exportCsvBtn').disabled = currentRows.length === 0;
  document.getElementById('exportJsonBtn').disabled = currentRows.length === 0;
}
```

(New searches always reset the refine filter — this matches the spec's "state flows" description; the filter narrows one fetched result set, it does not persist across searches.)

Replace `currentRows` with `visibleRows` in `totalPages`, `renderPage` (the two lines that slice/count rows), `exportCsv`, and `exportJson`:

```javascript
function totalPages() {
  return Math.max(1, Math.ceil(visibleRows.length / pageSize));
}
```

In `renderPage`, replace:
```javascript
  const pageRows = currentRows.slice(start, start + pageSize);
```
with:
```javascript
  const pageRows = visibleRows.slice(start, start + pageSize);
```
and:
```javascript
  const total = currentRows.length;
```
with:
```javascript
  const total = visibleRows.length;
```

In `exportCsv`, replace `currentRows.map(...)` with `visibleRows.map(...)`. In `exportJson`, replace:
```javascript
  downloadBlob(JSON.stringify(currentRows, null, 2), 'log_search_results.json', 'application/json');
```
with:
```javascript
  downloadBlob(JSON.stringify(visibleRows, null, 2), 'log_search_results.json', 'application/json');
```

- [ ] **Step 4: Wire up live event listeners**

Near the other `addEventListener` calls at the bottom of `app/static/js/log_search.js`, add:

```javascript
document.getElementById('refineFilterInput').addEventListener('input', applyRefineFilter);
document.getElementById('refineFilterMode').addEventListener('change', applyRefineFilter);
document.getElementById('refineFilterNegate').addEventListener('change', applyRefineFilter);
```

- [ ] **Step 5: Manually verify in-browser**

Reload Log Search, run a search that returns multiple rows with at least two different source IPs (e.g. broaden the source-IP box or time range). Then:
- Type a substring of one source IP into the filter box — confirm the table narrows live, the "Showing X–Y of Z" count updates, and pagination updates.
- Check "Negate" — confirm the row set inverts.
- Switch mode to "Regex", enter `^10\.` — confirm only matching rows show.
- Enter an invalid regex like `(` — confirm the inline error appears and the table keeps its last valid state (doesn't crash/blank out).
- Clear the filter box — confirm the full result set returns.
- With a filter active, click "Export CSV" and "Export JSON" — confirm both exported files contain only the filtered rows.
- Run a new search — confirm the filter box/negate/error reset and the new full result set displays.

- [ ] **Step 6: Commit**

```bash
git add app/templates/log_search.html app/static/js/log_search.js app/static/css/style.css
git commit -m "log-search: add live simple/regex refine filter with negate over fetched results"
```

---

### Task 3: Column visibility picker (persisted, non-pinned columns only)

**Files:**
- Modify: `app/templates/log_search.html` (add "Columns" button + popover markup)
- Modify: `app/static/js/log_search.js` (popover logic, `localStorage` persistence, filtering `currentColumns` for render)
- Modify: `app/static/css/style.css` (style the popover)

**Interfaces:**
- Consumes: `currentColumns` (Task 1), `buildColumns` (Task 1), `visibleRows`/`cellValue` (Task 1/2).
- Produces:
  - `hiddenColumns`: a `Set<string>` of raw field names, loaded from/synced to `localStorage['logSearchHiddenColumns']` (JSON array).
  - `renderedColumns()`: returns `currentColumns.filter((c) => c.isVirtual || !hiddenColumns.has(c.raw))` — used by `renderPage`/`exportCsv` instead of `currentColumns` directly, so hidden columns disappear from display/export while `currentColumns` (and thus the refine filter's `rowMatches`, which is unaffected by this task) still sees every column.

- [ ] **Step 1: Add "Columns" button and popover markup**

In `app/templates/log_search.html`, inside `.table-controls-right` (currently just the two export buttons, around line 94–97), add the Columns button before the export buttons:

```html
<div class="table-controls-right">
  <div class="columns-picker">
    <button type="button" class="btn btn-sm btn-secondary" id="columnsBtn">Columns</button>
    <div class="columns-popover hidden" id="columnsPopover"></div>
  </div>
  <button class="btn btn-sm btn-secondary" id="exportCsvBtn" disabled>Export CSV</button>
  <button class="btn btn-sm btn-secondary" id="exportJsonBtn" disabled>Export JSON</button>
</div>
```

- [ ] **Step 2: Style the popover**

In `app/static/css/style.css`, add after the `.refine-filter-error { ... }` rule from Task 2:

```css
.columns-picker { position: relative; }
.columns-popover {
  position: absolute;
  right: 0;
  top: calc(100% + .3rem);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow);
  padding: .5rem .75rem;
  min-width: 180px;
  max-height: 300px;
  overflow-y: auto;
  z-index: 50;
}
.columns-popover label {
  display: flex;
  align-items: center;
  gap: .4rem;
  font-size: .85rem;
  font-weight: 400;
  padding: .25rem 0;
  white-space: nowrap;
}
.columns-popover-empty {
  font-size: .8rem;
  color: var(--text-muted);
}
```

- [ ] **Step 3: Implement hidden-columns state, popover rendering, and toggle wiring**

In `app/static/js/log_search.js`, add near the top with the other module-level state:

```javascript
const HIDDEN_COLUMNS_KEY = 'logSearchHiddenColumns';

function loadHiddenColumns() {
  try {
    const raw = localStorage.getItem(HIDDEN_COLUMNS_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function saveHiddenColumns() {
  localStorage.setItem(HIDDEN_COLUMNS_KEY, JSON.stringify([...hiddenColumns]));
}

let hiddenColumns = loadHiddenColumns();

function renderedColumns() {
  return currentColumns.filter((c) => c.isVirtual || !hiddenColumns.has(c.raw));
}

function renderColumnsPopover() {
  const popover = document.getElementById('columnsPopover');
  const nonPinned = currentColumns.filter((c) => !c.isVirtual);
  if (nonPinned.length === 0) {
    popover.innerHTML = '<div class="columns-popover-empty">No extra columns</div>';
    return;
  }
  popover.innerHTML = nonPinned.map((c) => `
    <label>
      <input type="checkbox" class="column-toggle" data-field="${escHtml(c.raw)}" ${hiddenColumns.has(c.raw) ? '' : 'checked'} />
      ${escHtml(c.label)}
    </label>
  `).join('');
  popover.querySelectorAll('.column-toggle').forEach((cb) => {
    cb.addEventListener('change', () => {
      const field = cb.dataset.field;
      if (cb.checked) hiddenColumns.delete(field);
      else hiddenColumns.add(field);
      saveHiddenColumns();
      renderPage();
    });
  });
}
```

Update `renderPage` to render the header/body from `renderedColumns()` instead of `currentColumns` directly (the refine filter in Task 2 still reads `currentColumns` inside `rowMatches`, unaffected):

```javascript
function renderPage() {
  const headerRow = document.getElementById('resultsHeaderRow');
  const body = document.getElementById('resultsBody');
  const columns = renderedColumns();
  headerRow.innerHTML = columns.map((c) => `<th>${escHtml(c.label)}</th>`).join('');

  const start = (currentPage - 1) * pageSize;
  const pageRows = visibleRows.slice(start, start + pageSize);
  body.innerHTML = pageRows.map((row) =>
    `<tr>${columns.map((c) => `<td>${escHtml(cellValue(c, row))}</td>`).join('')}</tr>`
  ).join('');

  const total = visibleRows.length;
  const pages = totalPages();
  document.getElementById('resultsSummary').textContent = total === 0
    ? 'No results'
    : `Showing ${start + 1}–${Math.min(start + pageSize, total)} of ${total}`;
  document.getElementById('pageIndicator').textContent = `Page ${currentPage} of ${pages}`;
  document.getElementById('firstPageBtn').disabled = currentPage <= 1;
  document.getElementById('prevPageBtn').disabled = currentPage <= 1;
  document.getElementById('nextPageBtn').disabled = currentPage >= pages;
  document.getElementById('lastPageBtn').disabled = currentPage >= pages;
}
```

Update `exportCsv` to also use `renderedColumns()` (export follows what's visible on screen, same principle as the refine filter's export behavior):

```javascript
function exportCsv() {
  const columns = renderedColumns();
  const header = columns.map((c) => c.label).join(',');
  const lines = visibleRows.map((row) =>
    columns.map((c) => `"${String(cellValue(c, row) ?? '').replace(/"/g, '""')}"`).join(',')
  );
  downloadBlob([header, ...lines].join('\n'), 'log_search_results.csv', 'text/csv');
}
```

Update `renderResults` to also call `renderColumnsPopover()` after `currentColumns` is rebuilt:

```javascript
function renderResults(result) {
  currentRows = result.rows;
  currentFields = result.fields;
  currentColumns = buildColumns(currentFields);
  visibleRows = currentRows;
  document.getElementById('refineFilterInput').value = '';
  document.getElementById('refineFilterNegate').checked = false;
  document.getElementById('refineFilterError').classList.add('hidden');
  renderColumnsPopover();
  currentPage = 1;
  renderPage();
  document.getElementById('truncatedBanner').classList.toggle('hidden', !result.truncated);
  document.getElementById('exportCsvBtn').disabled = currentRows.length === 0;
  document.getElementById('exportJsonBtn').disabled = currentRows.length === 0;
}
```

Add popover open/close wiring near the other event listeners at the bottom of the file:

```javascript
document.getElementById('columnsBtn').addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('columnsPopover').classList.toggle('hidden');
});
document.addEventListener('click', (e) => {
  const picker = document.querySelector('.columns-picker');
  if (picker && !picker.contains(e.target)) {
    document.getElementById('columnsPopover').classList.add('hidden');
  }
});
```

- [ ] **Step 4: Manually verify in-browser**

Reload Log Search, run a search that returns at least one non-pinned (extra) field. Then:
- Click "Columns" — confirm a popover lists every non-pinned field as a checked checkbox, and the button toggles the popover open/closed.
- Uncheck one — confirm that column disappears from the table immediately and stays out of "Export CSV".
- Click elsewhere on the page — confirm the popover closes.
- Reload the page and re-run the same search — confirm the previously-hidden column is still hidden (localStorage persistence).
- Re-open "Columns" and re-check it — confirm it reappears and stays visible on the next search too.
- With a column hidden, type a filter term that only matches that hidden column's value — confirm the row still filters correctly (hiding a column doesn't remove it from the refine-filter match, since `rowMatches` reads `currentColumns`, not `renderedColumns()`).
- Run a search under a different log type with different extra fields — confirm the popover lists that log type's non-pinned fields, and any previously-hidden field name that happens to also appear here is still hidden (global-by-field-name persistence).

- [ ] **Step 5: Commit**

```bash
git add app/templates/log_search.html app/static/js/log_search.js app/static/css/style.css
git commit -m "log-search: add persisted column visibility picker for non-pinned columns"
```

---

## Post-plan cleanup check

After Task 3, confirm no dead code remains: `FIELD_LABELS`, `PINNED_FIELDS`, and the old `orderFields` function should no longer exist anywhere in `app/static/js/log_search.js` (removed in Task 1). Grep to confirm:

```bash
grep -n "PINNED_FIELDS\|FIELD_LABELS\|orderFields" app/static/js/log_search.js
```

Expected: no matches.
