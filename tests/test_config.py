import importlib
import os


def test_config_requires_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    import app.config as config_mod
    with __import__("pytest").raises(RuntimeError):
        importlib.reload(config_mod)
    # restore for subsequent tests in the same process
    os.environ["SECRET_KEY"] = "test-secret-key-for-ci"
    importlib.reload(config_mod)


def test_config_loads_defaults(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "a-real-secret")
    import app.config as config_mod
    importlib.reload(config_mod)
    assert config_mod.Config.SECRET_KEY == "a-real-secret"
    assert config_mod.Config.SESSION_COOKIE_HTTPONLY is True
    assert config_mod.Config.PERMANENT_SESSION_LIFETIME == 3600
