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
