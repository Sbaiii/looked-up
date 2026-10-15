"""Running dbt in-process: the arguments, the environment and the refresh flow, with dbt replaced by a fake."""
from __future__ import annotations

import json
import sys
import types
from datetime import date

from lookedup import warehouse as W


def _fake_dbt(monkeypatch, success=True, exception=None):
    calls = []

    class Runner:
        def invoke(self, args):
            calls.append(args)
            return types.SimpleNamespace(success=success, exception=exception)

    mod = types.ModuleType("dbt.cli.main")
    mod.dbtRunner = Runner
    monkeypatch.setitem(sys.modules, "dbt.cli.main", mod)
    return calls


def test_run_passes_project_and_vars(monkeypatch, tmp_path):
    monkeypatch.setattr(W, "WAREHOUSE_DB", tmp_path / "w.duckdb")
    calls = _fake_dbt(monkeypatch)
    assert W.run(["build", "--select", "stg_hourly"]) is True
    args = calls[0]
    assert args[:3] == ["build", "--select", "stg_hourly"]
    assert args[args.index("--project-dir") + 1] == str(W.WAREHOUSE_DIR)
    assert json.loads(args[args.index("--vars") + 1])["lake_root"] == str(W.LOCAL_LAKE_DIR)
    import os
    assert os.environ["LOOKEDUP_WAREHOUSE_DB"] == str(tmp_path / "w.duckdb")


def test_run_on_the_hub_and_failures(monkeypatch, tmp_path):
    import pytest

    monkeypatch.setattr(W, "WAREHOUSE_DB", tmp_path / "w.duckdb")
    calls = _fake_dbt(monkeypatch, success=False)
    assert W.run(["test"], hf=True) is False
    assert json.loads(calls[0][calls[0].index("--vars") + 1])["lake_root"] == f"hf://datasets/{W.HF_REPO_ID}"
    _fake_dbt(monkeypatch, exception=RuntimeError("compilation error"))
    with pytest.raises(RuntimeError, match="compilation"):
        W.run(["build"])
