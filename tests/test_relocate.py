from __future__ import annotations

from lookedup.relocate import relocate


def test_relocate_moves_files_and_leaves_a_note(tmp_path):
    src, dst = tmp_path / "repo-data", tmp_path / "outside"
    (src / "lake" / "data").mkdir(parents=True)
    (src / "lake" / "data" / "manifest.json").write_text("{}")
    (src / "warehouse").mkdir()
    (src / "warehouse" / "db.duckdb").write_bytes(b"x" * 1000)
    (src / "raw").mkdir()
    (src / "raw" / "big.gz").write_bytes(b"y")
    res = relocate(src, dst, skip=("raw",))
    assert res["moved"] == 2 and res["skipped"] == 1
    assert (dst / "lake" / "data" / "manifest.json").read_text() == "{}"
    assert (dst / "warehouse" / "db.duckdb").stat().st_size == 1000
    assert not (src / "lake").exists() and (src / "raw" / "big.gz").exists()
    assert str(dst) in (src / "README.md").read_text()
    assert relocate(dst, dst)["moved"] == 0


def test_db_connections_cap_spill(tmp_path, monkeypatch):
    from lookedup import db

    con = db.connect()
    assert con.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0] in ("20.0 GiB", "20GiB", "21.4 GB")
