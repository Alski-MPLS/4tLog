"""Navigation tab registry — single source of truth for nav metadata.

Each blueprint self-registers at import time:

    from app import registry
    registry.register("my_tab", "My Tab", "myblueprint.myview")

The app factory then injects ``nav_registry`` into every template and
syncs ``groups.KNOWN_TABS`` from this registry.
"""

from __future__ import annotations

_registry: dict[str, dict] = {}


def register(key: str, name: str, endpoint: str, icon: str = "") -> None:
    _registry[key] = {"name": name, "endpoint": endpoint, "icon": icon}


def get_registry() -> dict[str, dict]:
    return dict(_registry)


def known_tabs() -> dict[str, str]:
    return {k: v["name"] for k, v in _registry.items()}
