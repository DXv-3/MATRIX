import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MATRIX_DATA_DIR", str(tmp_path / "matrix_test"))
    monkeypatch.setenv("MATRIX_ENV", "development")
    monkeypatch.delenv("MATRIX_API_TOKEN", raising=False)
    from matrix.settings import reload_settings

    reload_settings()