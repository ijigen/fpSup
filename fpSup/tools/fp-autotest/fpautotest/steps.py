# SPDX-License-Identifier: GPL-3.0-or-later
"""Execution of individual harness steps.

Each supported step kind is handled by one small function.  Failures are
reported as ``StepResult(ok=False, ...)`` rather than raised, so the runner can
continue through a suite when ``continue_on_fail`` is set.
"""

from __future__ import annotations

import re
import time

from .plan import Step
from .runner import StepResult

_SNIPPET = 300


def _as_int(value: object, field: str) -> int:
    """Parse an int or hex string (``"0xC007F324"`` / ``"C007F324"``)."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer, not a bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} is empty")
        try:
            return int(text, 16)  # accepts an optional 0x prefix
        except ValueError as exc:
            raise ValueError(f"{field} is not a hex integer: {value!r}") from exc
    raise ValueError(f"{field} must be an integer or hex string, got {type(value).__name__}")


def _word(value: int) -> str:
    if 0 <= value <= 0xFFFFFFFF:
        return f"0x{value:08X}"
    return f"0x{value:X}"


def _snippet(text: str, limit: int = _SNIPPET) -> str:
    flat = text.replace("\r", " ").replace("\n", " ")
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def _result(
    step: Step, ok: bool, detail: str, observation: str = "", index: int = -1
) -> StepResult:
    return StepResult(
        index=index, kind=step.kind, ok=ok, detail=detail, observation=observation
    )


def _shell(step: Step, session: object) -> StepResult:
    command = step.params.get("command")
    if not isinstance(command, str) or not command.strip():
        return _result(step, False, "shell step needs a non-empty 'command'")

    try:
        reply = session.sh(command)
    except Exception as exc:  # transport failures are step failures
        return _result(step, False, f"shell command failed: {exc}")

    contains = step.params.get("expect_contains")
    regex = step.params.get("expect_regex")

    if contains is not None:
        expected = str(contains)
        if expected not in reply:
            return _result(
                step,
                False,
                f"expected reply to contain {expected!r}; "
                f"observed {_snippet(reply)!r}",
                reply,
            )

    if regex is not None:
        pattern = str(regex)
        try:
            matched = re.search(pattern, reply) is not None
        except re.error as exc:
            return _result(step, False, f"invalid expect_regex {pattern!r}: {exc}", reply)
        if not matched:
            return _result(
                step,
                False,
                f"expected reply to match /{pattern}/; "
                f"observed {_snippet(reply)!r}",
                reply,
            )

    if contains is not None and regex is not None:
        detail = f"reply contained {str(contains)!r} and matched /{regex}/"
    elif contains is not None:
        detail = f"reply contained {str(contains)!r}"
    elif regex is not None:
        detail = f"reply matched /{regex}/"
    else:
        detail = "command succeeded"
    return _result(step, True, detail, reply)


def _mem_expect(step: Step, session: object) -> StepResult:
    try:
        addr = _as_int(step.params.get("addr"), "addr")
        value = _as_int(step.params.get("value"), "value")
        size = int(step.params.get("size", 4))
    except (ValueError, TypeError) as exc:
        return _result(step, False, f"invalid mem_expect parameters: {exc}")

    try:
        observed = session.mem_get(addr, size)
    except Exception as exc:
        return _result(step, False, f"mem_get 0x{addr:08X} failed: {exc}")

    observation = _word(observed)
    ok = observed == value
    detail = (
        f"addr 0x{addr:08X}: expected {_word(value)}, observed {_word(observed)}"
    )
    return _result(step, ok, detail, observation)


def _mem_expect_any(step: Step, session: object) -> StepResult:
    raw_values = step.params.get("values")
    if not isinstance(raw_values, (list, tuple)) or not raw_values:
        return _result(step, False, "mem_expect_any needs a non-empty 'values' list")
    try:
        addr = _as_int(step.params.get("addr"), "addr")
        values = [_as_int(item, "values[]") for item in raw_values]
        size = int(step.params.get("size", 4))
    except (ValueError, TypeError) as exc:
        return _result(step, False, f"invalid mem_expect_any parameters: {exc}")

    try:
        observed = session.mem_get(addr, size)
    except Exception as exc:
        return _result(step, False, f"mem_get 0x{addr:08X} failed: {exc}")

    observation = _word(observed)
    expected = " or ".join(_word(item) for item in values)
    ok = observed in values
    detail = f"addr 0x{addr:08X}: expected {expected}, observed {_word(observed)}"
    return _result(step, ok, detail, observation)


def _status_expect(step: Step, session: object) -> StepResult:
    name = step.params.get("name")
    if not isinstance(name, str) or not name.strip():
        return _result(step, False, "status_expect needs a non-empty 'name'")
    if "value" not in step.params:
        return _result(step, False, "status_expect needs a 'value'")
    expected = str(step.params["value"])

    try:
        observed = session.status(name)
    except Exception as exc:
        return _result(step, False, f"status get {name} failed: {exc}")

    ok = observed == expected
    detail = f"status {name!r}: expected {expected!r}, observed {observed!r}"
    return _result(step, ok, detail, observed)


def _prompt(step: Step, session: object, *, interactive: bool, input_fn) -> StepResult:
    message = step.params.get("message", "")
    message = str(message)
    print(message)
    if not interactive:
        return _result(
            step, False, f"interactive input required for prompt: {message!r}"
        )
    try:
        answer = input_fn(message)
    except Exception as exc:
        return _result(step, False, f"prompt input failed: {exc}")
    return _result(
        step, True, f"operator acknowledged prompt: {message!r}", str(answer)
    )


def _wait(step: Step) -> StepResult:
    raw = step.params.get("seconds")
    if isinstance(raw, bool):
        return _result(step, False, "wait 'seconds' must be a number")
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return _result(step, False, f"wait needs a numeric 'seconds', got {raw!r}")
    if not 0.0 <= seconds <= 600.0:
        return _result(step, False, f"wait seconds out of range 0..600: {seconds}")

    time.sleep(seconds)
    return _result(step, True, f"waited {seconds:g}s")


def execute(step: Step, session: object, *, interactive: bool, input_fn) -> StepResult:
    """Execute one step and return its result (never raises for step failures)."""
    if step.kind == "shell":
        return _shell(step, session)
    if step.kind == "mem_expect":
        return _mem_expect(step, session)
    if step.kind == "mem_expect_any":
        return _mem_expect_any(step, session)
    if step.kind == "status_expect":
        return _status_expect(step, session)
    if step.kind == "prompt":
        return _prompt(step, session, interactive=interactive, input_fn=input_fn)
    if step.kind == "wait":
        return _wait(step)
    return _result(step, False, f"unknown step kind {step.kind!r}")
