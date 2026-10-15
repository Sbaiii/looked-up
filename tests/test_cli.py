"""The command line: argument parsing and dispatch, with the work functions replaced by fakes."""
from __future__ import annotations

import re
from datetime import datetime

import pytest

from lookedup import cli


def test_hour_argument_formats():
    want = datetime(2026, 10, 6, 14)
    for s in ("2026-10-06T14:00", "2026-10-06 14", "2026-10-06T14", "2026-10-06T14:37:12Z"):
        assert cli._hour(s) == want, s


def test_every_documented_command_is_registered(monkeypatch, capsys):
    documented = re.findall(r"^  ([a-z][a-z0-9-]+)\s", cli.__doc__, re.M)
    assert len(documented) >= 25
    for name in documented:
        with pytest.raises(SystemExit) as e:
            cli.main([name, "--help"])
        assert e.value.code == 0, name
    capsys.readouterr()


def test_unknown_command_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["no-such-command"])
    assert e.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_hourly_passes_its_options(monkeypatch):
    from lookedup import hourly, store

    seen = {}
    monkeypatch.setattr(store, "open_store", lambda local=False: f"store(local={local})")
    monkeypatch.setattr(hourly, "run", lambda st, window_hours, max_hours: seen.update(st=st, w=window_hours, m=max_hours) or 0)
    cli.main(["hourly", "--local", "--window", "48", "--max-hours", "3"])
    assert seen == {"st": "store(local=True)", "w": 48, "m": 3}


def test_backfill_builds_the_backfill_argv(monkeypatch):
    import lookedup.backfill as bf

    seen = []
    monkeypatch.setattr(bf, "main", lambda argv: seen.append(argv))
    cli.main(["backfill", "--from", "2026-07-09", "--to", "2026-07-10", "--local", "--oldest-first"])
    cli.main(["backfill", "--from", "2026-07-09", "--to", "2026-07-09", "--keep-raw"])
    assert seen == [["--from", "2026-07-09", "--to", "2026-07-10", "--local", "--oldest-first"],
                    ["--from", "2026-07-09", "--to", "2026-07-09", "--keep-raw"]]


def test_score_one_hour(monkeypatch, capsys):
    import lookedup.scorer as sc
    from lookedup import store

    seen = {}
    monkeypatch.setattr(store, "open_store", lambda local=False: "lake")
    monkeypatch.setattr(sc, "score", lambda st, max_hours, hours: seen.update(hours=hours, m=max_hours) or {"ok": 1})
    cli.main(["score", "--hour", "2026-10-08T14:00"])
    assert seen == {"hours": [datetime(2026, 10, 8, 14)], "m": cli.MAX_HOURS_PER_RUN}
    assert '"ok": 1' in capsys.readouterr().out
    cli.main(["score"])
    assert seen["hours"] is None


def test_warehouse_exit_code(monkeypatch):
    import lookedup.warehouse as wh

    calls = []
    monkeypatch.setattr(wh, "run", lambda args, hf=False: calls.append((args, hf)) or False)
    with pytest.raises(SystemExit) as e:
        cli.main(["warehouse", "test", "--select", "stg_hourly"])
    assert e.value.code == 1
    monkeypatch.setattr(wh, "run", lambda args, hf=False: calls.append((args, hf)) or True)
    cli.main(["warehouse", "--hf"])
    assert calls == [(["test", "--select", "stg_hourly"], False), (["build"], True)]


def test_live_snapshot_without_a_host(monkeypatch, caplog):
    import lookedup.live_analysis as la

    monkeypatch.delenv("LIVE_URL", raising=False)
    monkeypatch.setattr(la, "snapshot", lambda *a: pytest.fail("must not snapshot without a host"))
    cli.main(["live-snapshot"])
    assert "LIVE_URL not set" in caplog.text
