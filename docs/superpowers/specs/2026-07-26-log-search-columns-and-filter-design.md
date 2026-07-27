# Log Search: fixed column ordering, refine filter, column visibility

Status: approved, not yet implemented.

## Problem

Log Search's results table currently orders columns as `[srcip, dstip, ...rest alphabetically]`
(`PINNED_FIELDS` in [app/static/js/log_search.js](../../../app/static/js/log_search.js)). There's
no way to further narrow a fetched result set without re-running the search against
FortiAnalyzer, and no way to hide columns the user doesn't care about.

## Scope

Client-side only (`app/static/js/log_search.js` + `app/templates/log_search.html` +
`app/static/css/style.css`). No backend/API changes — all three features operate on the
result set already returned by `POST /api/log-search`.

## 1. Fixed column ordering (virtual/merged columns)

Replace `PINNED_FIELDS`/`orderFields()` with a definition of 6 pinned *virtual* columns, each
built from one or more raw fields, evaluated in this order:

| # | Virtual column | Built from (first match wins per row) | Display |
|---|---|---|---|
| 1 | Date/Time | `date`+`time` if both present, else first present of `itime`, `eventtime`, `date` | merged string |
| 2 | Source | `srcip` (+ `srcname`/`srchost` if present & non-empty) | `"name (ip)"` or just `ip` |
| 3 | Destination | `dstip` (+ `dstname`/`dsthost` if present & non-empty) | same pattern |
| 4 | Port | `dstport` + `service` | `"443/HTTPS"`, or whichever of the two exists |
| 5 | Action | `action` | raw value |
| 6 | Firewall | `devname`, fallback `devid` | raw value |

A virtual column is included only if at least one of its source fields exists anywhere in the
current result set's field list — same "skip if absent" behavior `orderFields()` has today for
`srcip`/`dstip`. All raw fields consumed by a virtual column are removed from the "remaining
fields" list so they don't also appear as their own raw column. Any fields not consumed by a
virtual column follow afterward in existing alphabetical order.

Field-name fallbacks (`srcname`/`srchost`, `itime`/`eventtime`) are a defensive guess — the
exact raw field names haven't been confirmed live against this deployment's FortiAnalyzer yet.
Confirmed live: current traffic logs return raw `srcip`/`dstip` only, no resolved name field.
Tighten the fallback list once real field names are observed for other log types.

## 2. Refine filter (client-side, over the already-fetched result set)

New row above the results table with:
- Text input (search term)
- Mode dropdown: **Contains** / **Regex**
- **Negate** checkbox

Behavior:
- Filters live, as-you-type (no submit step).
- Matches against all column values in each row, string-concatenated, case-insensitive.
- Regex mode compiles `new RegExp(term, 'i')`; an invalid pattern shows an inline error next to
  the input and leaves the previous filter result in place (does not throw/crash the page).
- Negate inverts the match (row is kept when it does *not* match).
- An empty term means no filter is applied (full result set shown).
- Filtering does not mutate `currentRows` (the raw fetched data). It produces a derived
  `visibleRows` array that pagination, the results-summary count, and both CSV/JSON export all
  read from — so export reflects exactly what's currently filtered/on-screen.

## 3. Column visibility picker

- A "Columns" button sits in `.table-controls-right`, next to the existing Export buttons.
- Clicking it opens a small checklist popover listing every **non-pinned** field present in the
  current result set (the 6 pinned virtual columns above are never listed — always shown,
  can't be hidden).
- Checked = visible; unchecking hides that column and re-renders the table immediately.
- The hidden-set is a flat list of raw field names, stored in `localStorage`
  (key: `logSearchHiddenColumns`), and applies **globally** across log types and searches — not
  scoped per log type. A hidden field name that isn't present in a given result set is simply a
  no-op.
- Popover closes on an outside click or picking a column; no explicit "Apply" button needed
  since it just toggles a checkbox state live.

## Interaction between the three features

- Column order (§1) determines which columns exist and their order.
- Column visibility (§3) is a filter on top of that column list for rendering — hidden columns
  are skipped when building the header row and each `<td>`, but a hidden column's value is still
  included in the refine filter's (§2) row-text match (hiding a column shouldn't make its data
  unsearchable).
- Refine filter (§2) never changes which columns are shown — only which rows.

## Testing

No backend changes, so no new pytest coverage. Manual verification in-browser:
1. Run a traffic-log search; confirm the 6 pinned columns appear in the specified order and any
   extra fields follow alphabetically.
2. Run an event-log search (no `srcip`/`dstport`); confirm the Source/Port pinned columns are
   omitted rather than rendering empty.
3. Enter a plain substring term (e.g. an IP) in the refine filter; confirm row count/pagination
   update live and CSV export matches what's on screen.
4. Enter a substring term (e.g. `8.8.8.8`) with Negate checked and confirm the inverse row set
   (everything NOT containing that IP) is shown; repeat with Regex mode for a pattern like
   `^10\.`.
5. Enter an invalid regex; confirm an inline error appears and the table doesn't break.
6. Hide a non-pinned column, reload the page, confirm it's still hidden (localStorage
   persistence), and confirm re-checking it in the popover restores it.
