from __future__ import annotations

import json
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from conftest import HOURLY_SAMPLE, LANGS

from lookedup.store import (
    LocalStore,
    Manifest,
    StoreConflict,
    day_path,
    expected_hours,
    merge_day,
    missing_hours,
    write_hours,
)
from lookedup.transform import SCHEMA, hourly_dump_to_table

H14 = datetime(2026, 9, 13, 14)


def _hour(ts: datetime, rows: list[tuple[str, str, int, int]]) -> pa.Table:
    return pa.table({"ts_hour_start": [ts] * len(rows), "lang": [r[0] for r in rows], "title": [r[1] for r in rows],
                     "views_desktop": [r[2] for r in rows], "views_mobile": [r[3] for r in rows]}).cast(SCHEMA)


def test_day_path_layout():
    assert day_path(datetime(2026, 10, 7, 9)) == "data/hourly/year=2026/month=10/day=07.parquet"
    assert day_path(datetime(2026, 10, 7, 23)) == day_path(datetime(2026, 10, 7, 0))


def test_expected_hours_only_completed_hours():
    now = datetime(2026, 10, 7, 12, 45)
    exp = expected_hours(now, 3)
    # the 12:00 hour is still running, so the last complete hour starts at 11:00
    assert exp == [datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 10), datetime(2026, 10, 7, 11)]
    assert len(expected_hours(now, 72)) == 72


def test_missing_hours_diff():
    m = Manifest()
    m.add(datetime(2026, 10, 7, 10), rows=1, source="hourly_dump")
    exp = expected_hours(datetime(2026, 10, 7, 12, 45), 3)
    assert missing_hours(m, exp) == [datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 11)]
    for ts in exp:
        m.add(ts, rows=1, source="pageview_complete")
    assert missing_hours(m, exp) == []


def test_manifest_roundtrip_and_merge():
    m = Manifest()
    m.add(datetime(2026, 10, 7, 9), rows=10, source="hourly_dump", ingested_at=datetime(2026, 10, 7, 12, 50))
    m.set_file(day_path(datetime(2026, 10, 7)), rows=10, size=100)
    doc = json.loads(m.to_json())
    assert doc["schema_version"] == 2 and doc["hour_count"] == 1 and doc["total_bytes"] == 100
    assert doc["hours"]["2026-10-07T09:00:00Z"] == {
        "path": "data/hourly/year=2026/month=10/day=07.parquet", "rows": 10,
        "source": "hourly_dump", "ingested_at": "2026-10-07T12:50:00Z"}
    m2 = Manifest.from_json(m.to_json())
    other = Manifest()
    other.add(datetime(2026, 10, 7, 10), rows=5, source="pageview_complete")
    m2.merge(other)
    assert m2.present() == {datetime(2026, 10, 7, 9), datetime(2026, 10, 7, 10)}


def test_manifest_rejects_unknown_source():
    with pytest.raises(ValueError):
        Manifest().add(datetime(2026, 1, 1), rows=0, source="api")


def test_merge_day_replaces_hours_and_sorts():
    h1, h2 = datetime(2026, 10, 7, 1), datetime(2026, 10, 7, 2)
    existing = pa.concat_tables([_hour(h1, [("fr", "B", 5, 0), ("en", "A", 9, 9)]), _hour(h2, [("en", "A", 1, 4)])])
    merged = merge_day(existing, [_hour(h2, [("en", "A", 7, 7), ("de", "Z", 3, 3)])])
    rows = list(zip(*(merged[c].to_pylist() for c in ("lang", "title", "ts_hour_start", "views_desktop")), strict=True))
    assert rows == [("de", "Z", h2, 3), ("en", "A", h1, 9), ("en", "A", h2, 7), ("fr", "B", h1, 5)]
    assert merged.schema == SCHEMA


def test_write_hours_appends_to_the_day_file(tmp_path, article_filter):
    store = LocalStore(tmp_path / "lake")
    table = hourly_dump_to_table(HOURLY_SAMPLE, H14, LANGS, article_filter)
    h15 = datetime(2026, 9, 13, 15)
    assert write_hours(store, {H14: (table, "hourly_dump")}, "a") == [H14]
    assert write_hours(store, {H14: (table, "hourly_dump")}, "again") == []      # idempotent
    t15 = table.set_column(0, "ts_hour_start", pa.array([h15] * table.num_rows, pa.timestamp("us")))
    assert write_hours(store, {h15: (t15, "pageview_complete")}, "b") == [h15]
    m = store.read_manifest()
    assert m.present() == {H14, h15}
    assert set(m.files) == {day_path(H14)}
    day = pq.read_table(tmp_path / "lake" / day_path(H14))
    assert day.num_rows == 2 * table.num_rows
    assert m.files[day_path(H14)]["rows"] == day.num_rows
    keys = list(zip(day["lang"].to_pylist(), day["title"].to_pylist(), day["ts_hour_start"].to_pylist(), strict=True))
    assert keys == sorted(keys)
    assert pq.ParquetFile(tmp_path / "lake" / day_path(H14)).metadata.row_group(0).column(0).compression == "ZSTD"


def test_write_hours_redoes_the_merge_after_a_conflict(tmp_path):
    """A concurrent writer's hour must survive: the merge is recomputed on the new state."""
    h1, h2 = datetime(2026, 10, 7, 1), datetime(2026, 10, 7, 2)

    class Racy(LocalStore):
        raced = False

        def commit(self, files, delta, message, parent=None):
            if not self.raced:  # another writer lands h1 just before our first commit
                self.raced = True
                write_hours(LocalStore(self.root), {h1: (_hour(h1, [("en", "A", 5, 5)]), "hourly_dump")}, "other")
                raise StoreConflict("raced")
            super().commit(files, delta, message, parent)

    store = Racy(tmp_path / "lake")
    assert write_hours(store, {h2: (_hour(h2, [("en", "B", 6, 6)]), "pageview_complete")}, "ours") == [h2]
    day = pq.read_table(tmp_path / "lake" / day_path(h1))
    assert sorted(day["title"].to_pylist()) == ["A", "B"]
    assert store.read_manifest().present() == {h1, h2}


def test_day_of_path():
    from datetime import date

    from lookedup.store import _day_of

    assert _day_of("data/hourly/year=2026/month=10/day=07.parquet") == date(2026, 10, 7)


def test_manifest_refuses_an_unknown_source():
    m = Manifest()
    with pytest.raises(ValueError):
        m.add(datetime(2026, 8, 17, 2), rows=10, source="scraped")
    m.add(datetime(2026, 8, 17, 2), rows=10, source="hourly_dump")
    assert m.has(datetime(2026, 8, 17, 2)) and not m.has(datetime(2026, 8, 17, 3))


def test_manifest_json_summary():
    m = Manifest()
    m.add(datetime(2026, 8, 17, 2), rows=10, source="hourly_dump")
    m.set_file("data/hourly/year=2026/month=08/day=17.parquet", rows=10, size=1234)
    doc = json.loads(m.to_json())
    assert doc["schema_version"] == 2 and doc["hour_count"] == 1 and doc["total_bytes"] == 1234
    assert Manifest.from_json(m.to_json()).hours == m.hours
    assert Manifest.from_json(None).hours == {} and Manifest.from_json("").files == {}


class _FakeApi:
    def __init__(self, files):
        self.files, self.commits = list(files), []

    def list_repo_files(self, repo_id, repo_type=None):
        return list(self.files)

    def create_commit(self, repo_id, repo_type=None, commit_message=None, operations=None, parent_commit=None):
        self.commits.append((commit_message, operations, parent_commit))


def _hf(api):
    from lookedup.store import HFStore
    hf = HFStore.__new__(HFStore)                     # no network: bypass the constructor
    hf.repo_id, hf.token, hf.api = "user/repo", "token", api
    return hf


def test_hub_store_prefix_listing_and_deletion():
    api = _FakeApi(["data/spikes/a.parquet", "data/hourly/b.parquet", "data/spikes/c.parquet"])
    hf = _hf(api)
    assert hf.list_prefix("data/spikes/") == ["data/spikes/a.parquet", "data/spikes/c.parquet"]
    assert hf.delete_prefix("data/spikes/", "drop") == ["data/spikes/a.parquet", "data/spikes/c.parquet"]
    assert len(api.commits) == 1 and len(api.commits[0][1]) == 2
    assert hf.delete_prefix("data/none/", "drop") == [] and len(api.commits) == 1      # nothing to delete: no commit


def test_hub_commit_maps_a_race_to_a_conflict(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from huggingface_hub.utils import HfHubHTTPError

    from lookedup.store import StoreConflict

    def failing(status):
        def create_commit(*a, **k):
            raise HfHubHTTPError("nope", response=SimpleNamespace(status_code=status, headers={}, request=None))
        return create_commit

    api = _FakeApi([])
    hf = _hf(api)
    monkeypatch.setattr(hf, "read_manifest", lambda revision=None: Manifest())
    for status in (409, 412):
        api.create_commit = failing(status)
        with pytest.raises(StoreConflict):
            hf.commit({}, Manifest(), "m", parent="abc")
    api.create_commit = failing(500)
    with pytest.raises(HfHubHTTPError):
        hf.commit({}, Manifest(), "m", parent="abc")


def test_hub_commit_needs_a_token():
    hf = _hf(_FakeApi([]))
    hf.token = None
    with pytest.raises(RuntimeError, match="HF token missing"):
        hf.commit({}, Manifest(), "m", parent="abc")


def test_sync_downloads_only_what_changed(tmp_path, monkeypatch):
    import huggingface_hub

    from lookedup.store import sync_to_local

    m = Manifest()
    for d, size in ((16, 10), (17, 20), (18, 30)):
        m.set_file(f"data/hourly/year=2026/month=08/day={d}.parquet", rows=1, size=size)
    hf = _hf(_FakeApi([]))
    monkeypatch.setattr(hf, "head", lambda: "rev1")
    monkeypatch.setattr(hf, "read_manifest", lambda revision=None: m)
    local = LocalStore(tmp_path)
    up_to_date = tmp_path / "data/hourly/year=2026/month=08/day=17.parquet"
    up_to_date.parent.mkdir(parents=True)
    up_to_date.write_bytes(b"x" * 20)
    got = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, path, **k: got.append((path, k["revision"])))
    res = sync_to_local(hf, local, datetime(2026, 8, 17), include_sitelinks=False)
    assert got == [("data/hourly/year=2026/month=08/day=18.parquet", "rev1")]           # day 16 is before the start
    assert res == {"downloaded": 1, "up_to_date": 1, "revision": "rev1", "hours": 0}
    assert local.read_manifest().files == m.files


def test_local_store_list_prefix(tmp_path):
    store = LocalStore(tmp_path)
    (tmp_path / "data" / "app" / "days").mkdir(parents=True)
    (tmp_path / "data" / "app" / "days" / "2026-08-17.json").write_text("{}")
    (tmp_path / "data" / "app" / "today.json").write_text("{}")
    assert store.list_prefix("data/app") == ["data/app/days/2026-08-17.json", "data/app/today.json"]
    assert store.list_prefix("data/none") == [] and store.head() is None


def test_merge_day_into_nothing(article_filter):
    table = hourly_dump_to_table(HOURLY_SAMPLE, H14, LANGS, article_filter)
    merged = merge_day(None, [table])
    keys = list(zip(merged["lang"].to_pylist(), merged["title"].to_pylist(), strict=True))
    assert merged.num_rows == table.num_rows and keys == sorted(keys)
    empty = table.slice(0, 0)
    assert merge_day(None, [empty]).num_rows == 0


def test_hub_fetch_missing_file(monkeypatch):
    import huggingface_hub
    from huggingface_hub.utils import EntryNotFoundError

    def missing(*a, **k):
        raise EntryNotFoundError("not there")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", missing)
    hf = _hf(_FakeApi([]))
    assert hf.fetch("data/manifest.json", None, "rev") is None
    assert hf.read_manifest("rev").hours == {}


def test_hf_token_prefers_the_environment(monkeypatch):
    import huggingface_hub

    from lookedup.store import hf_token

    monkeypatch.setattr(huggingface_hub, "get_token", lambda: "saved")
    monkeypatch.setenv("HF_TOKEN", "from-env")
    assert hf_token() == "from-env"
    monkeypatch.delenv("HF_TOKEN")
    assert hf_token() == "saved"


def test_hub_store_creation(monkeypatch):
    import huggingface_hub

    from lookedup import store as S

    created = []

    class Api:
        def __init__(self, token=None):
            self.token = token

        def repo_exists(self, repo_id, repo_type=None):
            return repo_id == "user/exists"

        def create_repo(self, repo_id, repo_type=None, private=None):
            created.append((repo_id, private))

    monkeypatch.setattr(huggingface_hub, "HfApi", Api)
    monkeypatch.setattr(S, "hf_token", lambda: None)
    with pytest.raises(RuntimeError, match="HF token missing"):
        S.HFStore("user/new", create=True)
    S.HFStore("user/exists", token="t", create=True)
    S.HFStore("user/new", token="t", create=True)
    assert created == [("user/new", False)]


def test_hub_maintenance_calls(tmp_path):
    from types import SimpleNamespace

    calls = []

    class Api(_FakeApi):
        def dataset_info(self, repo_id, expand=None):
            return SimpleNamespace(sha="abc", used_storage=123)

        def super_squash_history(self, repo_id, repo_type=None, commit_message=None):
            calls.append(("squash", repo_type))

        def upload_file(self, path_or_fileobj=None, path_in_repo=None, repo_id=None, repo_type=None, commit_message=None):
            calls.append(("card", path_in_repo, repo_type))

    hf = _hf(Api([]))
    assert hf.head() == "abc" and hf.used_storage() == 123
    hf.squash_history("squash")
    hf.upload_card(tmp_path / "README.md")
    assert calls == [("squash", "dataset"), ("card", "README.md", "dataset")]


def test_sync_includes_sitelinks(tmp_path, monkeypatch):
    import huggingface_hub

    from lookedup.settings import SITELINKS_PATH
    from lookedup.store import sync_to_local

    hf = _hf(_FakeApi([]))
    monkeypatch.setattr(hf, "head", lambda: "rev")
    monkeypatch.setattr(hf, "read_manifest", lambda revision=None: Manifest())
    got = []
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", lambda repo, path, **k: got.append(path))
    sync_to_local(hf, LocalStore(tmp_path), datetime(2026, 8, 1))
    sync_to_local(hf, LocalStore(tmp_path), datetime(2026, 8, 1), include_sitelinks=False)
    assert got == [SITELINKS_PATH]


def test_hub_commit_sends_files_and_merged_manifest(tmp_path, monkeypatch):
    import json
    from datetime import timedelta
    from types import SimpleNamespace

    from lookedup.store import MANIFEST_PATH

    api = _FakeApi([])
    sent = []
    api.create_commit = lambda repo_id, **k: sent.append(k) or SimpleNamespace(oid="0123456789abcdef")
    hf = _hf(api)
    old = Manifest()
    old.add(H14, rows=3, source="hourly_dump")
    monkeypatch.setattr(hf, "read_manifest", lambda revision=None: old)
    src = tmp_path / "day.parquet"
    src.write_bytes(b"x")
    delta = Manifest()
    delta.add(H14 + timedelta(hours=1), rows=4, source="hourly_dump")
    hf.commit({"data/hourly/x.parquet": src}, delta, "data: 1 hour", parent="abc")
    [k] = sent
    assert k["parent_commit"] == "abc" and k["commit_message"] == "data: 1 hour" and k["repo_type"] == "dataset"
    assert [op.path_in_repo for op in k["operations"]] == ["data/hourly/x.parquet", MANIFEST_PATH]
    manifest = Manifest.from_json(k["operations"][-1].path_or_fileobj.decode())
    assert manifest.present() == {H14, H14 + timedelta(hours=1)}
    assert json.loads(k["operations"][-1].path_or_fileobj)


def test_write_hours_gives_up_after_repeated_conflicts(tmp_path, monkeypatch):
    import lookedup.store as S

    tries = []

    class AlwaysRaced(LocalStore):
        def commit(self, files, delta, message, parent=None):
            tries.append(parent)
            raise StoreConflict("raced again")

    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="could not commit after 3 attempts: ours"):
        write_hours(AlwaysRaced(tmp_path / "lake"), {H14: (_hour(H14, [("en", "A", 1, 1)]), "hourly_dump")}, "ours",
                    attempts=3)
    assert len(tries) == 3


def test_open_store_local_or_hub(monkeypatch):
    import lookedup.store as S

    made = []
    monkeypatch.setattr(S, "HFStore", lambda **k: made.append(k) or "hub")
    assert isinstance(S.open_store(local=True), LocalStore) and made == []
    assert S.open_store() == "hub" and made == [{"create": True}]
