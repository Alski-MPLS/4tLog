# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

4tLog is an early-stage project to build a log-search tool against Fortinet FortiAnalyzer (FAZ) over its JSON-RPC API. The user should be able to query FAZ traffic logs by source/destination IP (single host, network/CIDR, range, or ANY/ALL, IPv4 or IPv6), by port (name like `HTTPS`, number, `tcp:443`/`udp:53`, range, or multiple entries), and by a time window (relative like `30m`/`2d`, or an explicit date range). Output should be human-readable and exportable to CSV or JSON with all available fields.

The current implementation is a single Ansible playbook that represents the "first working slice" of this flow — it is a scaffold for endpoint/permission discovery against a real FAZ appliance, not a finished feature. See [plan.md](plan.md) for the original spec and [ansible/readme.md](ansible/readme.md) for a full description of the playbook's current behavior, variables, and troubleshooting steps.

## Repository layout

- `ansible/faz_log_search.yml` — the playbook. Builds a JSON-RPC request from filter inputs, runs a `logview` preflight check, submits a log search (`method: add`), polls for completion (`method: get`), and writes the result to `ansible/output/`.
- `ansible/my-vault.yml` — Ansible Vault–encrypted credentials file (do not decrypt/print contents into chat or commits).
- `ansible/output/` — generated JSON exports from playbook runs; not meant to be hand-edited.
- `api-info/*.json` — official FortiAnalyzer 7.6.7 Swagger/OpenAPI specs for the `eventmgmt`, `fortiview`, and `logview` modules. These are the authoritative reference for available JSON-RPC resources, parameters, and response schemas — consult them before guessing at an API shape.
- `api-info/site.md` — short primer on the FAZ JSON-RPC message format (request/response envelope: `id`, `method`, `params`, `session`; response `status.code` of `0` means success).

## Running the playbook

```bash
ansible-playbook ansible/faz_log_search.yml --extra-vars 'faz_api_key=YOUR_API_KEY'
```

Prefer the vaulted credentials file over passing the key on the command line:

```bash
ansible-playbook ansible/faz_log_search.yml -e @ansible/my-vault.yml --ask-vault-pass
```

Test FAZ appliance: `192.168.64.4` (test creds live outside this repo / in the vault file — do not hardcode them into the playbook or commit them in plaintext).

Key overridable variables (via `--extra-vars`): `faz_host`, `faz_port`, `faz_adom`, `faz_rpc_resource`, `faz_fetch_uri_candidates`, `faz_source_ips`, `faz_destination_ips`, `faz_ports`, `faz_time_window`, `faz_start_time`/`faz_end_time`, `faz_max_logs`, `faz_output_format`. When passing lists/objects, use JSON syntax for `--extra-vars` (a single JSON blob) rather than `key=value` pairs so types are preserved.

There is no lint/test suite in this repo yet; validate playbook changes with `ansible-playbook --syntax-check ansible/faz_log_search.yml` and by running against the test FAZ host.

## Architecture notes

- FortiAnalyzer's JSON-RPC log search is asynchronous: a submit call (`method: add`) returns a task ID (`tid`), and results are fetched by polling `method: get` against a URL that includes the `tid` until `result.percentage == 100`. The playbook implements this submit → poll → fetch loop with retries/delay controlled by `faz_search_timeout_seconds` and `faz_poll_delay_seconds`.
- The exact resource path and payload shape for log search (`faz_rpc_resource`, `faz_preflight_resource`) are **not yet finalized** — FAZ permissions and firmware version affect which route is exposed to a given API key. The playbook is deliberately built to make this discoverable: it runs a `logview` preflight before the full search and fails with a diagnostic message (`No permission for the resource`) rather than silently proceeding, and `faz_fetch_uri_candidates` exists so alternate endpoint paths can be probed. When adjusting these, check `api-info/*.json` first for the documented shape, and see the "Capture Exact GUI API Calls" section of [ansible/readme.md](ansible/readme.md) for how to reverse-engineer the exact request from the FAZ web UI's network traffic if the documented shape doesn't match observed behavior.
- Source/destination IP and port filters are translated into a FortiAnalyzer filter expression string (e.g. `srcip==10.1.1.0/24 and dstport==443`) inside the `Build the log filter expression` task in the playbook — `ANY`/`ALL` values are treated as "no filter" and omitted from the clause list.
- Time filters are normalized into a `faz_time_range` fact: explicit `faz_start_time`/`faz_end_time` take priority, then relative windows (`\d+m`, `\d+h`, `\d+d` are pattern-matched and converted to `last-n-minutes`/`last-n-hours`), else a default of `last-n-hours: 24`.
- Output is currently JSON-only, written to `ansible/output/faz_log_search.json` by default (`faz_output_dir`/`faz_output_file` are overridable). CSV export is planned but not yet implemented — the spec calls for a human-readable output as well as CSV/JSON export.
