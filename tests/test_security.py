from pathlib import Path

import pytest

from matrix.security import PathValidationError, resolve_directory


def test_resolve_directory_rejects_etc(tmp_path: Path):
    with pytest.raises(PathValidationError):
        resolve_directory("/etc")


def test_resolve_directory_ok(tmp_path: Path):
    d = tmp_path / "archive"
    d.mkdir()
    assert resolve_directory(str(d)) == d.resolve()