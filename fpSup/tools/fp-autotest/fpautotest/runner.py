# SPDX-License-Identifier: GPL-3.0-or-later
"""Suite orchestration and result reporting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from .plan import Suite


@dataclass
class StepResult:
    index: int
    kind: str
    ok: bool
    detail: str
    observation: str


@dataclass
class RunResult:
    suite_name: str
    ok: bool
    steps: tuple[StepResult, ...]
    started: str
    ended: str


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _report_stem(suite_name: str) -> str:
    return suite_name.replace("/", "_").replace("\\", "_").strip() or "suite"


def _md_cell(text: str) -> str:
    flat = text.replace("\r", " ").replace("\n", "<br>").replace("|", "\\|")
    return flat or "-"


def _write_reports(report_dir: Path, suite: Suite, result: RunResult) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = _report_stem(suite.name)

    payload = {
        "suite": result.suite_name,
        "description": suite.description,
        "ok": result.ok,
        "started": result.started,
        "ended": result.ended,
        "steps": [asdict(step) for step in result.steps],
    }
    (report_dir / f"{stem}-result.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    lines = [
        f"# {suite.name}",
        "",
    ]
    if suite.description:
        lines.extend([suite.description, ""])
    lines.extend(
        [
            f"- Result: {'PASS' if result.ok else 'FAIL'}",
            f"- Started: {result.started}",
            f"- Ended: {result.ended}",
            f"- Steps: {len(result.steps)}",
            "",
            "| # | Kind | Result | Detail | Observation |",
            "|---|------|--------|--------|-------------|",
        ]
    )
    for step in result.steps:
        lines.append(
            f"| {step.index} | {step.kind} | "
            f"{'PASS' if step.ok else 'FAIL'} | "
            f"{_md_cell(step.detail)} | {_md_cell(step.observation)} |"
        )
    lines.append("")
    (report_dir / f"{stem}-report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def run_suite(
    suite: Suite,
    session: object,
    *,
    interactive: bool = True,
    report_dir: str | Path | None = None,
    input_fn=input,
) -> RunResult:
    """Run every step in ``suite`` against ``session``.

    Stops at the first failure unless that step sets
    ``continue_on_fail: true`` in its params.
    """
    from .steps import execute  # local import avoids a module cycle

    started = _timestamp()
    results: list[StepResult] = []

    for index, step in enumerate(suite.steps):
        result = execute(
            step, session, interactive=interactive, input_fn=input_fn
        )
        result = replace(result, index=index)
        results.append(result)
        if not result.ok and not bool(step.params.get("continue_on_fail", False)):
            break

    ok = len(results) == len(suite.steps) and all(item.ok for item in results)
    run = RunResult(
        suite_name=suite.name,
        ok=ok,
        steps=tuple(results),
        started=started,
        ended=_timestamp(),
    )

    if report_dir is not None:
        _write_reports(Path(report_dir), suite, run)

    return run
