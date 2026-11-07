# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the fp-autotest harness.  No camera and no USB are touched.

The CLI and runner are exercised with a scripted fake session.  Transport
construction is limited to frame encoding/decoding and the upstream putfile
import path; opening a real device is never attempted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fpautotest import cli  # noqa: E402
from fpautotest.plan import Step, Suite, load_suite  # noqa: E402
from fpautotest.runner import run_suite  # noqa: E402
from fpautotest.session import (  # noqa: E402
    DaemonSession,
    DirectSession,
    ShellError,
    build_frame,
    default_backend,
    open_session,
    parse_frame,
)
from fpautotest.steps import _as_int, execute  # noqa: E402

HEADER = 20


class FakeSession:
    """A scripted session: replies by exact shell line, words by address."""

    def __init__(self, replies=None, memory=None, statuses=None):
        self.replies = dict(replies or {})
        self.memory = dict(memory or {})
        self.statuses = dict(statuses or {})
        self.commands = []
        self.closed = False

    def sh(self, line):
        self.commands.append(line)
        value = self.replies.get(line, "")
        if isinstance(value, Exception):
            raise value
        return value

    def mem_get(self, addr, size=4):
        self.commands.append(("mem_get", addr, size))
        if addr not in self.memory:
            raise ShellError(f"no scripted word at 0x{addr:08X}")
        return self.memory[addr]

    def status(self, name=""):
        self.commands.append(("status", name))
        return self.statuses.get(name, "")

    def version(self):
        return self.sh("version")

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _suite(*steps, name="unit-suite", description="unit test"):
    return Suite(name=name, description=description, steps=list(steps))


def _write_json_suite(tmp_path, steps, name="json-suite"):
    path = tmp_path / "suite.json"
    path.write_text(
        json.dumps({"name": name, "description": "json test", "steps": steps}),
        encoding="utf-8",
    )
    return path


# -- plan ----------------------------------------------------------------


def test_load_json_suite(tmp_path):
    path = _write_json_suite(
        tmp_path,
        [
            {"kind": "shell", "command": "version", "expect_contains": "5.02"},
            {"kind": "mem_expect", "addr": "0xC007F324", "value": "0xE309C6FC"},
        ],
    )
    suite = load_suite(path)
    assert suite.name == "json-suite"
    assert [step.kind for step in suite.steps] == ["shell", "mem_expect"]
    assert suite.steps[0].params["command"] == "version"


def test_load_yaml_suite_lexpo():
    pytest.importorskip("yaml")
    suite = load_suite(ROOT / "suites" / "lexpo.yaml")
    assert suite.name == "lexpo-fp502"
    assert [step.kind for step in suite.steps] == [
        "shell",
        "mem_expect",
        "mem_expect_any",
        "prompt",
        "wait",
    ]
    assert suite.steps[1].params["addr"] == "0xC007F324"
    assert suite.steps[2].params["values"] == ["0xE24DD064", "0xEB11CCD5"]
    assert suite.steps[-1].params["seconds"] == 90


def test_missing_pyyaml_is_a_clear_error(tmp_path, monkeypatch):
    path = tmp_path / "suite.yaml"
    path.write_text("name: x\nsteps: []\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(ValueError, match="PyYAML"):
        load_suite(path)


def test_unknown_step_kind_rejected(tmp_path):
    path = _write_json_suite(tmp_path, [{"kind": "reboot"}])
    with pytest.raises(ValueError, match="unknown kind"):
        load_suite(path)


def test_unsupported_extension_rejected(tmp_path):
    path = tmp_path / "suite.txt"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported suite extension"):
        load_suite(path)


# -- steps ---------------------------------------------------------------


def test_as_int_accepts_hex_forms():
    assert _as_int("0xC007F324", "addr") == 0xC007F324
    assert _as_int("C007F324", "addr") == 0xC007F324
    assert _as_int(7, "value") == 7
    with pytest.raises(ValueError):
        _as_int("not-hex", "addr")
    with pytest.raises(ValueError):
        _as_int(True, "addr")


def test_shell_step_pass_and_fail():
    session = FakeSession(replies={"version": "fp 5.02.0 build"})
    good = execute(
        Step("shell", {"command": "version", "expect_contains": "5.02.0"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert good.ok

    bad = execute(
        Step("shell", {"command": "version", "expect_regex": "5\\.03"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert not bad.ok
    assert "expected reply to match" in bad.detail


def test_shell_transport_error_is_step_failure():
    session = FakeSession(replies={"version": ShellError("no daemon")})
    result = execute(
        Step("shell", {"command": "version"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert not result.ok
    assert "no daemon" in result.detail


def test_mem_expect_pass_and_fail():
    session = FakeSession(memory={0xC007F324: 0xE309C6FC})
    good = execute(
        Step("mem_expect", {"addr": "0xC007F324", "value": "0xE309C6FC"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert good.ok

    bad = execute(
        Step("mem_expect", {"addr": "0xC007F324", "value": "0x00000000"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert not bad.ok
    assert "observed 0xE309C6FC" in bad.detail


def test_mem_expect_any():
    session = FakeSession(memory={0xC02BAD0C: 0xE24DD064})
    result = execute(
        Step(
            "mem_expect_any",
            {"addr": "0xC02BAD0C", "values": ["0xE24DD064", "0xEB11CCD5"]},
        ),
        session,
        interactive=False,
        input_fn=input,
    )
    assert result.ok

    session.memory[0xC02BAD0C] = 0x12345678
    result = execute(
        Step(
            "mem_expect_any",
            {"addr": "0xC02BAD0C", "values": ["0xE24DD064", "0xEB11CCD5"]},
        ),
        session,
        interactive=False,
        input_fn=input,
    )
    assert not result.ok


def test_status_expect():
    session = FakeSession(statuses={"fpSup": "running"})
    good = execute(
        Step("status_expect", {"name": "fpSup", "value": "running"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert good.ok
    bad = execute(
        Step("status_expect", {"name": "fpSup", "value": "stopped"}),
        session,
        interactive=False,
        input_fn=input,
    )
    assert not bad.ok


def test_prompt_requires_interactive_mode():
    step = Step("prompt", {"message": "press Enter"})
    failed = execute(step, FakeSession(), interactive=False, input_fn=lambda _: "")
    assert not failed.ok
    assert "interactive input required" in failed.detail

    passed = execute(step, FakeSession(), interactive=True, input_fn=lambda _: "ok")
    assert passed.ok
    assert passed.observation == "ok"


def test_wait_zero_seconds():
    result = execute(
        Step("wait", {"seconds": 0}), FakeSession(), interactive=False, input_fn=input
    )
    assert result.ok


# -- runner --------------------------------------------------------------


def test_runner_stops_at_first_failure():
    suite = _suite(
        Step("mem_expect", {"addr": 0x10, "value": 0xAA}),
        Step("shell", {"command": "version"}),
    )
    session = FakeSession(memory={0x10: 0xBB}, replies={"version": "ok"})
    result = run_suite(suite, session, interactive=False, input_fn=input)
    assert not result.ok
    assert len(result.steps) == 1


def test_runner_continue_on_fail():
    suite = _suite(
        Step(
            "mem_expect",
            {"addr": 0x10, "value": 0xAA, "continue_on_fail": True},
        ),
        Step("shell", {"command": "version"}),
    )
    session = FakeSession(memory={0x10: 0xBB}, replies={"version": "ok"})
    result = run_suite(suite, session, interactive=False, input_fn=input)
    assert not result.ok
    assert len(result.steps) == 2


def test_runner_writes_reports(tmp_path):
    suite = _suite(Step("shell", {"command": "version"}))
    session = FakeSession(replies={"version": "fp 5.02.0"})
    result = run_suite(
        suite, session, interactive=False, input_fn=input, report_dir=tmp_path
    )
    assert result.ok
    payload = json.loads((tmp_path / "unit-suite-result.json").read_text())
    assert payload["ok"] is True
    assert payload["steps"][0]["kind"] == "shell"
    markdown = (tmp_path / "unit-suite-report.md").read_text()
    assert "| 0 | shell | PASS |" in markdown


# -- transport -----------------------------------------------------------


def test_frame_round_trip():
    frame = build_frame(0x12345678, 3, b"shl version")
    assert len(frame) == 64
    parsed = parse_frame(frame)
    assert parsed["command"] == 3
    assert parsed["sequence"] == 0x12345678
    assert parsed["payload"].startswith(b"shl version")


def test_frame_payload_spills_past_64_bytes():
    payload = b"shl " + b"x" * 100
    frame = build_frame(1, 3, payload)
    assert len(frame) > 64
    parsed = parse_frame(frame[:64])
    assert parsed["payload_length"] == len(payload)
    assert parsed["payload"] == payload[:44]


def test_frame_crc_rejects_corruption():
    frame = bytearray(build_frame(1, 3, b"shl version"))
    frame[HEADER] ^= 0xFF
    with pytest.raises(ShellError, match="CRC"):
        parse_frame(bytes(frame))


@pytest.mark.parametrize("session_cls", [DaemonSession, DirectSession])
def test_mem_get_parses_shell_reply(session_cls):
    session = object.__new__(session_cls)
    replies = {
        "mem get 0xC007F324,,4": (
            "get : A:0xC007F324, D:0xE309C6FC\n"
            "get : A:0xC007F328, D:0x11111111"
        )
    }
    session.sh = lambda line: replies[line]
    assert session.mem_get(0xC007F324) == 0xE309C6FC


def test_mem_get_rejects_unparseable_reply():
    session = object.__new__(DaemonSession)
    session.sh = lambda line: "no such address"
    with pytest.raises(ShellError, match="cannot parse"):
        session.mem_get(0xC007F324)


def test_default_backend_follows_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert default_backend() == "daemon"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert default_backend() == "daemon"
    monkeypatch.setattr(sys, "platform", "win32")
    assert default_backend() == "direct"


def test_open_session_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown backend"):
        open_session("carrier-pigeon")


def test_daemon_session_uses_upstream_putfile():
    session = DaemonSession()
    assert callable(session._putfile.sh)
    assert isinstance(session._putfile.SOCK, str)
    session.close()


# -- CLI -----------------------------------------------------------------


def test_cli_list_shows_builtin_suite(capsys):
    assert cli.main(["list"]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "lexpo.yaml" in combined


def test_cli_list_can_use_json_suite(tmp_path, monkeypatch, capsys):
    _write_json_suite(tmp_path, [{"kind": "shell", "command": "version"}])
    monkeypatch.setattr(cli, "SUITES_DIR", tmp_path)
    assert cli.main(["list"]) == 0
    assert "json-suite" in capsys.readouterr().out


def test_cli_run_pass(tmp_path, monkeypatch, capsys):
    path = _write_json_suite(
        tmp_path,
        [
            {"kind": "shell", "command": "version", "expect_contains": "5.02.0"},
            {"kind": "mem_expect", "addr": "0x10", "value": "0xAA"},
        ],
    )
    session = FakeSession(
        replies={"version": "fp 5.02.0"}, memory={0x10: 0xAA}
    )
    monkeypatch.setattr(cli, "_make_session", lambda backend, timeout: session)
    assert cli.main(["run", str(path), "--non-interactive"]) == 0
    out = capsys.readouterr().out
    assert "backend:" in out
    assert "[PASS] 1. shell" in out
    assert "json-suite: PASS (2/2 steps)" in out


def test_cli_run_failure_exit_code(tmp_path, monkeypatch):
    path = _write_json_suite(
        tmp_path, [{"kind": "mem_expect", "addr": "0x10", "value": "0xAA"}]
    )
    session = FakeSession(memory={0x10: 0xBB})
    monkeypatch.setattr(cli, "_make_session", lambda backend, timeout: session)
    assert cli.main(["run", str(path), "--non-interactive"]) == 1


def test_cli_run_missing_suite_exit_code():
    assert cli.main(["run", "definitely-not-a-suite"]) == 2


def test_cli_run_prompt_fails_non_interactive(tmp_path, monkeypatch):
    path = _write_json_suite(tmp_path, [{"kind": "prompt", "message": "do it"}])
    monkeypatch.setattr(
        cli, "_make_session", lambda backend, timeout: FakeSession()
    )
    assert cli.main(["run", str(path), "--non-interactive"]) == 1


def test_cli_doctor(monkeypatch, capsys):
    session = FakeSession(
        replies={"version": "fp 5.02.0"}, statuses={"": "idle"}
    )
    monkeypatch.setattr(cli, "_make_session", lambda backend, timeout: session)
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "version: fp 5.02.0" in out
    assert "doctor: OK" in out


def test_cli_doctor_transport_failure(monkeypatch):
    def explode(backend, timeout):
        raise ShellError("no camera")

    monkeypatch.setattr(cli, "_make_session", explode)
    assert cli.main(["doctor"]) == 2


def test_cli_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    assert "fpautotest" in capsys.readouterr().out
