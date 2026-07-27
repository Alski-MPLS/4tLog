# Changelog

## 2026-07-26

### Added

- Log Search results table now pins six columns first — Date/Time, Source,
  Destination, Port, Action, Firewall — in that order, before any other
  returned fields.
- Log Search: a live refine filter above the results table narrows an
  already-fetched search without re-querying FortiAnalyzer. Supports plain
  substring or regex matching, with a Negate option, and applies to
  pagination, the row count, and CSV/JSON export.
- Log Search: a "Columns" picker lets you show/hide non-pinned columns; the
  choice is remembered in your browser across searches and log types.
