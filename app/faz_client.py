"""FortiAnalyzer JSON-RPC client — read-only health/status calls.

Authenticates with Authorization: Bearer <token>. This header, not
X-API-Key, is what FortiAnalyzer's /jsonrpc endpoint actually recognizes —
confirmed by direct curl comparison against the test appliance
(192.168.64.4) while debugging ansible/faz_log_search.yml: X-API-Key and
no-auth-header-at-all produced byte-identical "-11 No permission" errors,
while Authorization: Bearer returned real data.

Only login()/logout()/preflight()/get_sys_status() are implemented here —
search_logs() and build_filter_expression() (ported from the Ansible
playbook's Jinja filter-building logic) are added in Phase 3 when the Log
Search tab is their first consumer.
"""

import requests
import urllib3


class FAZError(Exception):
    """Raised when FortiAnalyzer returns a non-zero status code, a JSON-RPC
    error envelope, or an unexpected response shape."""


class FAZClient:
    def __init__(
        self,
        host: str,
        token: str,
        adom: str = "root",
        verify_ssl: bool = True,
        timeout: int = 30,
        port: int = 443,
        preflight_resource: str | None = None,
    ):
        self.host = host
        self.port = port
        self.token = token
        self.adom = adom
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.preflight_resource = preflight_resource or f"/logview/adom/{adom}/logfields"
        self.base_url = f"https://{host}:{port}/jsonrpc"
        self._req_id = 0
        self._http = requests.Session()
        if not verify_ssl:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    def _post(self, body: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        resp = self._http.post(
            self.base_url,
            json=body,
            headers=headers,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _unwrap_result(data: dict) -> dict:
        if "error" in data:
            raise FAZError(f"FortiAnalyzer error: {data['error']}")
        result = data.get("result")
        if isinstance(result, list):
            result = result[0] if result else {}
        if not isinstance(result, dict):
            raise FAZError(f"Unexpected FortiAnalyzer response shape: {data!r}")
        status = result.get("status", {})
        if status.get("code", -1) != 0:
            raise FAZError(status.get("message", "Unknown FortiAnalyzer error"))
        return result

    def login(self) -> "FAZClient":
        # Bearer token auth — no session login call needed.
        return self

    def logout(self) -> None:
        self._http.close()

    def __enter__(self) -> "FAZClient":
        return self.login()

    def __exit__(self, *_exc) -> None:
        self.logout()

    def preflight(self) -> bool:
        """Connectivity/permission check against the logview module.

        Ported from the Ansible playbook's preflight task
        (ansible/faz_log_search.yml). Returns True if the account can read
        logview resources; raises FAZError otherwise — most commonly with
        status code -11 "No permission for the resource".
        """
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "get",
            "params": [
                {
                    "url": self.preflight_resource,
                    "apiver": 3,
                    "devtype": "FortiGate",
                    "logtype": "traffic",
                }
            ],
            "session": None,
        }
        self._unwrap_result(self._post(body))
        return True

    def get_sys_status(self) -> dict:
        """Return FortiAnalyzer /sys/status: hostname, version, serial, HA
        mode, disk usage. The exact field names in the returned dict are
        NOT covered by the Swagger specs in api-info/ (those only document
        logview/eventmgmt/fortiview) and must be validated live against
        the test appliance as part of this phase's validation step
        (Task 9) before the Dashboard is considered complete.
        """
        body = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "get",
            "params": [{"url": "/sys/status"}],
            "session": None,
        }
        result = self._unwrap_result(self._post(body))
        return result.get("data", {})
