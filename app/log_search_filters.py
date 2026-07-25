"""Pure parsing/validation for Log Search IP and port/service filter input.

Translates user-entered filter boxes into FortiAnalyzer filter-expression
clause fragments, ported from ansible/faz_log_search.yml's "Build the log
filter expression" Jinja task and extended to support explicit IP/port
ranges (plan.md's originally stated scope, which the playbook itself never
implemented).
"""

from __future__ import annotations

import ipaddress
import re

_PORT_RE = re.compile(r"^\d+$")
_PROTO_PORT_RE = re.compile(r"^(?:tcp|udp):(\d+)$", re.IGNORECASE)
_PROTO_RANGE_RE = re.compile(r"^(?:tcp|udp):(\d+)-(\d+)$", re.IGNORECASE)


class FilterValidationError(ValueError):
    """Raised with a message naming the exact offending input token."""


def _split_entries(raw: str) -> list[str]:
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def parse_ip_entries(raw: str, field: str) -> list[str]:
    clauses = []
    for entry in _split_entries(raw):
        if "-" in entry and "/" not in entry:
            start_str, _, end_str = entry.partition("-")
            start_str, end_str = start_str.strip(), end_str.strip()
            try:
                start = ipaddress.ip_address(start_str)
                end = ipaddress.ip_address(end_str)
            except ValueError as exc:
                raise FilterValidationError(f"Invalid IP range '{entry}': {exc}") from exc
            if start.version != end.version:
                raise FilterValidationError(
                    f"Invalid IP range '{entry}': start and end must be the same IP version"
                )
            if int(start) > int(end):
                raise FilterValidationError(
                    f"Invalid IP range '{entry}': start must not be greater than end"
                )
            clauses.append(f"({field}>={start} and {field}<={end})")
            continue
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                clauses.append(f"{field}=={network}")
            else:
                addr = ipaddress.ip_address(entry)
                clauses.append(f"{field}=={addr}")
        except ValueError as exc:
            raise FilterValidationError(f"Invalid IP/CIDR '{entry}': {exc}") from exc
    return clauses


def parse_port_entries(raw: str) -> list[str]:
    clauses = []
    for entry in _split_entries(raw):
        range_match = _PROTO_RANGE_RE.match(entry)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end:
                raise FilterValidationError(
                    f"Invalid port range '{entry}': start must not be greater than end"
                )
            clauses.append(f"(dstport>={start} and dstport<={end})")
            continue
        if _PORT_RE.match(entry):
            clauses.append(f"dstport=={entry}")
            continue
        proto_match = _PROTO_PORT_RE.match(entry)
        if proto_match:
            clauses.append(f"dstport=={proto_match.group(1)}")
            continue
        clauses.append(f'service=="{entry}"')
    return clauses
