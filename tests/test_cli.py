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


def test_live_commands_default_days(monkeypatch, capsys):
    import lookedup.dumps as dumps
    import lookedup.live_analysis as la
    from lookedup import store

    seen = {}
    monkeypatch.setattr(dumps, "utcnow", lambda: datetime(2026, 10, 12, 3, 30))
    monkeypatch.setattr(store, "open_store", lambda local=False: "lake")
    monkeypatch.setattr(la, "snapshot", lambda st, url, day: seen.update(snap=(url, day)) or {})
    monkeypatch.setattr(la, "append_scores", lambda st, day: seen.update(score=day) or {})
    cli.main(["live-snapshot", "--url", "https://live.example"])
    cli.main(["live-score"])
    assert seen == {"snap": ("https://live.example", datetime(2026, 10, 11).date()), "score": datetime(2026, 10, 10).date()}
    capsys.readouterr()


def test_evaluate_modes(monkeypatch, capsys):
    from lookedup.evaluation import run

    monkeypatch.setattr(run, "audit_sample", lambda: 100)
    monkeypatch.setattr(run, "audit_score", lambda: {"h3": "inconclusive"})
    monkeypatch.setattr(run, "evaluate", lambda: {"h1": "rejected"})
    cli.main(["evaluate", "--audit-sample"])
    cli.main(["evaluate", "--audit-score"])
    cli.main(["evaluate"])
    out = capsys.readouterr().out
    assert "100 units written" in out and '"h3": "inconclusive"' in out and '"h1": "rejected"' in out


def test_sync_options(monkeypatch, capsys):
    import lookedup.store as store

    seen = []
    monkeypatch.setattr(store, "HFStore", lambda: "hub")
    monkeypatch.setattr(store, "LocalStore", lambda: "local")
    monkeypatch.setattr(store, "sync_to_local", lambda hf, lo, since, include_sitelinks: seen.append((since, include_sitelinks)) or {})
    cli.main(["sync", "--from", "2026-07-09"])
    cli.main(["sync", "--from", "2026-07-09", "--no-sitelinks"])
    assert seen == [(datetime(2026, 7, 9), True), (datetime(2026, 7, 9), False)]
    capsys.readouterr()


def test_app_export_modes(monkeypatch, tmp_path, capsys):
    import lookedup.app_export as ax
    import lookedup.settings as settings
    from lookedup import store

    calls = []
    monkeypatch.setattr(store, "open_store", lambda local=False: f"store({local})")
    monkeypatch.setattr(ax, "export_live", lambda st: calls.append(("live", st)) or {"ok": 1})
    monkeypatch.setattr(ax, "backfill", lambda st, out: calls.append(("backfill", st)) or {"days": 0})
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    cli.main(["app-export"])
    cli.main(["app-export", "--backfill", "--local"])
    assert calls == [("live", "store(False)"), ("backfill", "store(True)")]
    capsys.readouterr()


def test_languages_command(monkeypatch, capsys):
    from datetime import date

    from lookedup import languages as L

    seen = {}
    monkeypatch.setattr(L, "rank_languages", lambda days, keep_raw=True: seen.update(days=days, keep=keep_raw) or
                        [{"rank": 1, "code": "en", "human_views_7d": 10, "mobile_share": 0.6, "automated_share": 0.0, "raw_rank": 1}])
    monkeypatch.setattr(L, "write_config", lambda ranking, days, top_n=30: seen.update(top_n=top_n))
    cli.main(["languages", "--today", "2026-10-08", "--top-n", "1"])
    assert seen["days"][0] == date(2026, 10, 1) and seen["days"][-1] == date(2026, 10, 7)
    assert seen["top_n"] == 1 and seen["keep"] is False
    assert "en" in capsys.readouterr().out


def test_hub_maintenance(monkeypatch, capsys):
    import json

    import lookedup.store as store

    actions = []

    class Hub:
        def __init__(self, create=False):
            pass

        def used_storage(self):
            return 100 - 10 * len(actions)

        def delete_prefix(self, prefix, message):
            actions.append(("drop", prefix))
            return [prefix + "a"]

        def squash_history(self, message):
            actions.append(("squash",))

    monkeypatch.setattr(store, "HFStore", Hub)
    cli.main(["hub"])
    assert actions == [] and json.loads(capsys.readouterr().out)["used_storage_after"] == 100
    cli.main(["hub", "--drop-prefix", "data/spikes/", "--squash"])
    res = json.loads(capsys.readouterr().out)
    assert actions == [("drop", "data/spikes/"), ("squash",)]
    assert res["used_storage_before"] == 100 and res["used_storage_after"] == 80 and res["squashed"] is True


def test_forecast_retrain_flags(monkeypatch, capsys):
    import lookedup.forecast.retrain as rt
    from lookedup import store

    seen = []
    monkeypatch.setattr(store, "open_store", lambda local=False: "lake")
    monkeypatch.setattr(rt, "retrain", lambda st, upload_batch, add_live_week: seen.append((upload_batch, add_live_week)) or {})
    cli.main(["forecast-retrain"])
    cli.main(["forecast-retrain", "--upload-batch", "--no-live"])
    assert seen == [(False, True), (True, False)]
    capsys.readouterr()


def test_relocate_data_skips(monkeypatch, capsys):
    import lookedup.relocate as rl

    seen = []
    monkeypatch.setattr(rl, "relocate", lambda skip=(): seen.append(skip) or {"moved": 0})
    cli.main(["relocate-data", "--skip", "raw", "--skip", "tmp"])
    assert seen == [("raw", "tmp")]
    capsys.readouterr()


def test_baselines_day(monkeypatch, capsys):
    from datetime import date

    import lookedup.dumps as dumps
    import lookedup.scorer as sc
    from lookedup import store

    seen = []
    monkeypatch.setattr(dumps, "utcnow", lambda: datetime(2026, 10, 12, 3, 30))
    monkeypatch.setattr(store, "open_store", lambda local=False: "lake")
    monkeypatch.setattr(sc, "build_baselines", lambda st, day: seen.append(day) or {})
    cli.main(["baselines"])
    cli.main(["baselines", "--day", "2026-10-01"])
    assert seen == [date(2026, 10, 12), date(2026, 10, 1)]
    capsys.readouterr()


def test_evaluate_v2_refresh(monkeypatch, capsys):
    from lookedup.evaluation import run_v2

    seen = []
    monkeypatch.setattr(run_v2, "evaluate", lambda refresh=False: seen.append(refresh) or {})
    cli.main(["evaluate-v2"])
    cli.main(["evaluate-v2", "--refresh"])
    assert seen == [False, True]
    capsys.readouterr()


def test_top_command(monkeypatch):
    import lookedup.query as q

    seen = []

    class Rel:
        def show(self, max_width=None):
            seen.append("shown")

    monkeypatch.setattr(q, "top", lambda lang, hour, n=20, local=False: seen.append((lang, hour, n, local)) or Rel())
    cli.main(["top", "--lang", "fr", "--hour", "2026-10-06 14", "-n", "5", "--local"])
    assert seen == [("fr", datetime(2026, 10, 6, 14), 5, True), "shown"]


def test_card_upload(monkeypatch):
    import lookedup.store as store
    from lookedup.settings import DATASET_CARD

    seen = []

    class Hub:
        def __init__(self, create=False):
            seen.append(("create", create))

        def upload_card(self, path):
            seen.append(("card", path))

    monkeypatch.setattr(store, "HFStore", Hub)
    cli.main(["card"])
    assert seen == [("create", True), ("card", DATASET_CARD)]


def test_verify_hour(monkeypatch, capsys):
    import json

    from lookedup import hourly

    monkeypatch.setattr(hourly, "verify_alignment", lambda ts, work: {"file": f"{ts:%H}", "dump_en_total": 1})
    cli.main(["verify-hour", "--hour", "2026-09-13T14:00"])
    assert json.loads(capsys.readouterr().out) == {"file": "14", "dump_en_total": 1}


def test_validate_exit_code(monkeypatch, capsys):
    import lookedup.backfill as bf
    from lookedup import store

    monkeypatch.setattr(store, "open_store", lambda local=False: "lake")
    monkeypatch.setattr(bf, "validate", lambda st, n, seed: [{"hour": "h", "matching_rows_pct": 99.995}])
    cli.main(["validate"])
    monkeypatch.setattr(bf, "validate", lambda st, n, seed: [{"hour": "h", "matching_rows_pct": 99.9}])
    with pytest.raises(SystemExit) as e:
        cli.main(["validate", "-n", "1"])
    assert e.value.code == 1
    capsys.readouterr()


def test_wikidata_upload_switch(monkeypatch, tmp_path, capsys):
    import lookedup.settings as settings
    import lookedup.wikidata as wd
    from lookedup import store

    commits = []

    class Lake:
        def commit(self, files, delta, message, parent=None):
            commits.append((list(files), message))

    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    monkeypatch.setattr(wd, "build_sitelinks", lambda langs, out: {"en": 2, "fr": 1})
    monkeypatch.setattr(store, "open_store", lambda local=False: Lake())
    cli.main(["wikidata", "--no-upload"])
    assert commits == []
    cli.main(["wikidata"])
    assert commits == [([settings.SITELINKS_PATH], "data: refresh Wikidata sitelinks (3 rows)")]
    capsys.readouterr()


def test_refresh_warehouse_exit_code(monkeypatch, capsys):
    import lookedup.warehouse as wh

    monkeypatch.setattr(wh, "refresh", lambda end=None: {"success": end is not None})
    with pytest.raises(SystemExit) as e:
        cli.main(["refresh-warehouse"])
    assert e.value.code == 1
    cli.main(["refresh-warehouse", "--end", "2026-10-10"])
    capsys.readouterr()
