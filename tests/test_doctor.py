import os

from matrix.doctor import run_doctor
from matrix.settings import load_env


def test_doctor_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("MATRIX_ENV", "development")
    monkeypatch.setenv("MATRIX_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MATRIX_SCAN_ROOTS", str(tmp_path))
    from matrix.settings import reload_settings

    reload_settings()
    report = run_doctor(fix=True)
    assert "checks" in report