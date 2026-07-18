# FortiAnalyzer Ansible Playbook

This folder contains a local Ansible playbook for querying FortiAnalyzer log data over the JSON-RPC API. The playbook is meant to be the first working slice of the 4tLog log-search flow:

- send a request to the FortiAnalyzer test host
- pass source IP, destination IP, port, and time filters
- print the raw response in the terminal
- write the response to a JSON export file under `ansible/output/`

The current playbook uses the FAZ test server at `192.168.64.4` and authenticates with an API key passed in at runtime. The exact log-search resource path is configurable because FortiAnalyzer permissions and firmware versions can change the route that is exposed to a given API key.

## Files

- `faz_log_search.yml` - the playbook that submits the FAZ request and saves the response
- `output/` - created automatically when the playbook writes exports

## What The Playbook Does

The playbook runs on `localhost` and posts a JSON-RPC request to `https://192.168.64.4/jsonrpc` using `Authorization: Bearer <API_KEY>`. It currently builds a request body with these inputs:

- source IPs
- destination IPs
- ports
- time window, start time, and end time placeholders
- max logs limit

The workflow is:

- submit search task (returns TID)
- probe configured fetch URI candidates
- select the first candidate accepted by the appliance
- poll results until complete

The final response is printed to the console and saved as JSON to `ansible/output/faz_log_search.json` by default.

## How To Run

Set the API key at runtime and execute the playbook from this folder or by using the full path:

```bash
ansible-playbook faz_log_search.yml --extra-vars 'faz_api_key=YOUR_API_KEY'
```

## Using Ansible Vault

If you do not want to pass credentials on the command line, store them in an encrypted file created with Ansible Vault. The file can include both the FAZ username and API key:

```yaml
faz_username: adminapi
faz_api_key: YOUR_API_KEY
```

Create the encrypted file with `ansible-vault` using any filename you prefer:

```bash
ansible-vault create my-vault.yml
```

To use the vaulted file, pass it with `-e` or `--extra-vars` and provide a vault password prompt or file:

```bash
ansible-playbook faz_log_search.yml -e @my-vault.yml --ask-vault-pass
```

Or, if you already have a vault password file:

```bash
ansible-playbook faz_log_search.yml -e @my-vault.yml --vault-password-file ~/.ansible_vault_pass
```

If you want to write the export somewhere else, override the output path:

```bash
ansible-playbook faz_log_search.yml \
	--extra-vars 'faz_api_key=YOUR_API_KEY faz_output_dir=/tmp/faz-export'
```

If you are passing lists or multiple query values, JSON syntax is safer because it preserves types:

```bash
ansible-playbook faz_log_search.yml \
	-e @my-vault.yml \
	--ask-vault-pass \
	--extra-vars '{"faz_source_ips":["10.1.1.0/24"],"faz_destination_ips":["any"],"faz_ports":["https"],"faz_time_window":"30m"}'
```

## Common Variables

You can override these values with `--extra-vars`:

- `faz_api_key` - API key for the FortiAnalyzer account
- `faz_host` - FAZ hostname or IP address
- `faz_port` - HTTPS port, default `443`
- `faz_adom` - ADOM name, default `root`
- `faz_rpc_resource` - JSON-RPC resource path to query
- `faz_fetch_uri_candidates` - ordered list of fetch URI candidates to try after TID creation
- `faz_source_ips` - list of source IPs, networks, or ranges
- `faz_destination_ips` - list of destination IPs, networks, or ranges
- `faz_ports` - list of ports or port expressions
- `faz_time_window` - relative time window such as `30m` or `2d`
- `faz_start_time` / `faz_end_time` - absolute date range values
- `faz_max_logs` - maximum number of records to request
- `faz_output_format` - currently `json`

Example with filters:

```bash
ansible-playbook faz_log_search.yml \
	--extra-vars '{"faz_api_key":"YOUR_API_KEY","faz_source_ips":["10.10.10.10"],"faz_destination_ips":["192.168.1.0/24"],"faz_ports":["HTTPS","tcp:443"],"faz_time_window":"30m"}'
```

Example with custom fetch URI candidates (for endpoint discovery):

```bash
ansible-playbook faz_log_search.yml \
	--extra-vars '{
	  "faz_api_key":"YOUR_API_KEY",
	  "faz_fetch_uri_candidates":[
	    "/logview/adom/root/logsearch/{{ faz_search_tid }}",
	    "/logview/adom/root/logsearch",
	    "/soc-fabric/logsearch/{{ faz_search_tid }}"
	  ]
	}'
```

## Notes

- The current playbook is a functional scaffold, not the final FAZ log-query implementation.
- If the FAZ account returns `No permission for the resource`, update `faz_rpc_resource` for the correct resource path or use an account with the required log access permissions.
- The playbook now fails explicitly when FAZ returns a non-zero status code in the JSON response body, so permission issues are easier to spot.
- The playbook probes multiple submit/fetch request formats and URI candidates automatically. If your FAZ build uses different paths, override `faz_fetch_uri_candidates` in `--extra-vars`.
- The playbook currently writes JSON output. CSV export can be added once the final response shape is confirmed.

## Capture Exact GUI API Calls

If endpoint discovery still fails, capture the exact JSON-RPC calls used by the FAZ web UI and mirror that shape in the playbook.

1. Log in to FAZ web UI in a desktop browser.
2. Open browser Developer Tools and go to the Network tab.
3. Filter requests by `jsonrpc`.
4. In the FAZ UI, run the same log search you are testing in Ansible:
	- source: `10.1.1.0/24`
	- destination: `ANY`
	- service/port: `HTTPS`
5. Find the submit request and the follow-up fetch/poll request.
6. For each request, copy either:
	- Request Payload JSON, or
	- Copy as cURL

When sharing back for playbook wiring, include:

- JSON `method` value (`add`, `get`, `exec`, etc.)
- exact key used in `params` (`url` or `uri`)
- full path used for submit and fetch
- whether task ID appears in path, params root, or `data`
- any required fields not currently in the playbook (`apiver`, `time-order`, etc.)

Tip: remove/redact sensitive values before sharing (cookies, authorization tokens, passwords).
