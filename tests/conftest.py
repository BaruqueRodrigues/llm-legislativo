from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def external_data_root(tmp_path, monkeypatch):
    """Keep integration-test artifacts outside the source checkout."""
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
