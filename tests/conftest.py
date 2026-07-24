import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci")
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True, scope="session")
def _preload_config():
    """Pre-import config module so tests can reload it."""
    import app.config  # noqa: F401
