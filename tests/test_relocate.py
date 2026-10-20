from __future__ import annotations

from pathlib import Path

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


def test_short_copy_is_retried(tmp_path, monkeypatch):
    import shutil

    from lookedup import relocate as R

    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 100)
    real = shutil.copyfile
    attempts = []

    def flaky(a, b):
        attempts.append(1)
        if len(attempts) == 1:
            Path(b).write_bytes(b"x" * 10)                 # a truncated first copy
            return b
        return real(a, b)

    monkeypatch.setattr(R.shutil, "copyfile", flaky)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    R._copy_with_retry(src, tmp_path / "out" / "dst.bin")
    assert len(attempts) == 2 and (tmp_path / "out" / "dst.bin").read_bytes() == b"x" * 100
    assert not (tmp_path / "out" / "dst.bin.part").exists()


def test_skipped_prefixes_stay_behind(tmp_path):
    from lookedup.relocate import relocate

    src, dst = tmp_path / "old", tmp_path / "new"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "big.gz").write_bytes(b"1")
    (src / "lake").mkdir()
    (src / "lake" / "m.json").write_text("{}")
    res = relocate(source=src, target=dst, skip=("raw",))
    assert (dst / "lake" / "m.json").exists() and not (dst / "raw").exists()
    assert (src / "raw" / "big.gz").exists() and res["moved"] == 1


def test_old_readme_stays(tmp_path):
    src, dst = tmp_path / "old", tmp_path / "new"
    src.mkdir()
    (src / "README.md").write_text("data moved")
    (src / "a.txt").write_text("a")
    res = relocate(source=src, target=dst)
    assert res["moved"] == 1 and (src / "README.md").exists() and not (dst / "README.md").exists()


def test_copy_gives_up(tmp_path, monkeypatch):
    import pytest

    from lookedup import relocate as R

    src = tmp_path / "src.bin"
    src.write_bytes(b"x")

    def broken(a, b):
        raise OSError("Operation timed out")

    monkeypatch.setattr(R.shutil, "copyfile", broken)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    with pytest.raises(OSError, match="timed out"):
        R._copy_with_retry(src, tmp_path / "dst.bin", retries=2)


def test_resume_skips_files_already_in_place(tmp_path, monkeypatch):
    from lookedup import relocate as R

    src, dst = tmp_path / "old", tmp_path / "new"
    (src / "lake").mkdir(parents=True)
    (src / "lake" / "a.parquet").write_bytes(b"12345")
    (dst / "lake").mkdir(parents=True)
    (dst / "lake" / "a.parquet").write_bytes(b"12345")                  # copied before the run was cut
    monkeypatch.setattr(R, "_copy_with_retry", lambda s, d: (_ for _ in ()).throw(AssertionError("no second copy")))
    res = R.relocate(source=src, target=dst)
    assert res["moved"] == 1 and res["bytes"] == 5 and not (src / "lake" / "a.parquet").exists()


def test_partial_target_file_is_replaced(tmp_path):
    src, dst = tmp_path / "old", tmp_path / "new"
    src.mkdir()
    (src / "a.bin").write_bytes(b"complete")
    dst.mkdir()
    (dst / "a.bin").write_bytes(b"comp")                                 # half-written by an earlier run
    assert relocate(source=src, target=dst)["moved"] == 1
    assert (dst / "a.bin").read_bytes() == b"complete"
