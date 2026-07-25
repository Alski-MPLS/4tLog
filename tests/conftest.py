import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
os.environ.setdefault("FAZ_HEALTH_POLL_DISABLED", "true")
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def clear_faz_health_cache():
    """Clear the faz_health_cache module-level cache before each test."""
    try:
        import app.faz_health_cache as cache_mod
        cache_mod._cache.clear()
    except ImportError:
        pass
    yield
    # Also clear after test to be safe
    try:
        import app.faz_health_cache as cache_mod
        cache_mod._cache.clear()
    except ImportError:
        pass
