# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line interface for the fpSup hardware-in-the-loop harness.

Usage::

    python -m fpautotest run <suite> [--backend daemon|direct]
                                    [--report DIR] [--non-interactive]
                                    [--timeout-ms N]
    python -m fpautotest doctor [--backend daemon|direct] [--timeout-ms N]
    python -m fpautotest list

Exit codes are ``0`` (pass), ``1`` (a step failed) and ``2`` (usage,
transport or suite-loading problem).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from .plan import Suite, load_suite
from .runner import RunResult, run_suite
from .session import (
    BACKENDS,
    DEFAULT_TIMEOUT_MS,
    default_backend,
    open_session,
)

SUITES_DIR = Path(__file__).resolve().parent.parent / "suites"

EXIT_OK = 0
EXIT_TEST_FAILURE = 1
EXIT_USAGE = 2

SUITE_SUFFIXES = (".yaml", ".yml", ".json")


def _no_input(_prompt: str) -> str:
    """Placeholder input function for ``--non-interactive`` runs."""
    return ""


def _positive_ms(text: str) -> int:
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("latin-1", errors="replace")
    return str(value)


def _one_line(text: str, limit: int = 200) -> str:
    flat = " ".join(text.split())
    return flat[:limit]


def _make_session(backend: str, timeout_ms: int | None):
    """Open a transport session; tests replace this with a fake session."""
    return open_session(backend, timeout_ms)


def _resolve_backend(value: str | None) -> str:
    return (value or default_backend()).lower()


# -- suite discovery -----------------------------------------------------


def _suite_files() -> list[Path]:
    if not SUITES_DIR.is_dir():
        return []
    return sorted(
        path
        for path in SUITES_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in SUITE_SUFFIXES
    )


def _suite_meta(path: Path) -> tuple[str, str] | None:
    """Return ``(name, description)`` or ``None`` when the file is unreadable."""
    try:
        suite: Suite = load_suite(path)
    except Exception:
        return None
    return suite.name, suite.description or ""


def _suite_error(path: Path) -> str:
    try:
        load_suite(path)
    except Exception as exc:
        return str(exc)
    return "unknown error"


def _resolve_suite(value: str) -> Path | None:
    """Resolve a suite path, built-in filename, or built-in suite ``name:``."""
    direct = Path(value)
    if direct.is_file():
        return direct

    for suffix in ("",) + SUITE_SUFFIXES:
        candidate = SUITES_DIR / f"{value}{suffix}"
        if candidate.is_file():
            return candidate

    for path in _suite_files():
        meta = _suite_meta(path)
        if meta is not None and meta[0] == value:
            return path
    return None


# -- commands ------------------------------------------------------------


def _print_run_result(result: RunResult) -> None:
    for position, step in enumerate(result.steps, 1):
        status = "PASS" if step.ok else "FAIL"
        print(f"[{status}] {position}. {step.kind} - {step.detail}")

    passed = sum(1 for step in result.steps if step.ok)
    total = len(result.steps)
    verdict = "PASS" if result.ok else "FAIL"
    print(f"{result.suite_name}: {verdict} ({passed}/{total} steps)")


def _cmd_run(args: argparse.Namespace) -> int:
    suite_path = _resolve_suite(args.suite)
    if suite_path is None:
        print(f"fp-autotest: suite not found: {args.suite}", file=sys.stderr)
        print(f"fp-autotest: built-in suites live in {SUITES_DIR}", file=sys.stderr)
        return EXIT_USAGE

    try:
        suite = load_suite(suite_path)
    except Exception as exc:
        print(f"fp-autotest: cannot load suite {suite_path}: {exc}", file=sys.stderr)
        return EXIT_USAGE

    interactive = not args.non_interactive
    input_fn = input if interactive else _no_input
    backend = _resolve_backend(args.backend)

    try:
        session = _make_session(backend, args.timeout_ms)
    except Exception as exc:
        print(
            f"fp-autotest: cannot open {backend} session: {exc}", file=sys.stderr
        )
        return EXIT_USAGE

    print(f"backend: {backend}")
    try:
        with session:
            result = run_suite(
                suite,
                session,
                interactive=interactive,
                report_dir=args.report,
                input_fn=input_fn,
            )
    except KeyboardInterrupt:
        print("fp-autotest: interrupted", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:
        print(f"fp-autotest: session error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    _print_run_result(result)
    if args.report is not None:
        print(f"report: {args.report}")
    return EXIT_OK if result.ok else EXIT_TEST_FAILURE


def _read_version(session: object) -> str:
    version_fn = getattr(session, "version", None)
    if callable(version_fn):
        return _as_text(version_fn())
    return _as_text(session.sh("version"))


def _read_status(session: object) -> str:
    """Ask for the read-only general status; no card is assumed mounted."""
    status_fn = getattr(session, "status", None)
    if callable(status_fn):
        try:
            return _as_text(status_fn(""))
        except TypeError:
            try:
                return _as_text(status_fn())
            except TypeError:
                pass
        except Exception:
            pass
    return _as_text(session.sh("status get"))


def _cmd_doctor(args: argparse.Namespace) -> int:
    backend = _resolve_backend(args.backend)
    try:
        session = _make_session(backend, args.timeout_ms)
    except Exception as exc:
        print(
            f"doctor: cannot open {backend} session: {exc}", file=sys.stderr
        )
        return EXIT_USAGE

    try:
        with session:
            version = _read_version(session)
            status = _read_status(session)
    except KeyboardInterrupt:
        print("doctor: interrupted", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:
        print(f"doctor: shell did not respond: {exc}", file=sys.stderr)
        return EXIT_USAGE

    version_line = _one_line(version)
    shell_ok = bool(version_line)
    print(f"backend: {backend}")
    print(f"version: {version_line or '(empty)'}")
    print(f"status: {_one_line(status) or '(empty)'}")
    print(f"shell: {'responsive' if shell_ok else 'no response'}")
    print("doctor: OK" if shell_ok else "doctor: shell did not respond")
    return EXIT_OK if shell_ok else EXIT_USAGE


def _cmd_list(_args: argparse.Namespace) -> int:
    files = _suite_files()
    if not files:
        print(f"fp-autotest: no built-in suites found in {SUITES_DIR}", file=sys.stderr)
        return EXIT_OK

    for path in files:
        meta = _suite_meta(path)
        if meta is None:
            print(
                f"{path.stem}  (unreadable suite: {_suite_error(path)})  [{path.name}]",
                file=sys.stderr,
            )
            continue
        name, description = meta
        suffix = f"  {description}" if description else ""
        print(f"{name}{suffix}  [{path.name}]")
    return EXIT_OK


# -- parser --------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fpautotest",
        description=(
            "Hardware-in-the-loop tests for SIGMA fp SUP cards over the fpSup "
            "USB shell."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="Run a suite against the camera"
    )
    run_parser.add_argument(
        "suite",
        help="Built-in suite name (for example lexpo-fp502) or a path to a suite file",
    )
    run_parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=None,
        help=(
            "Transport backend (default: daemon on macOS/Linux, direct on "
            "Windows)"
        ),
    )
    run_parser.add_argument(
        "--report",
        metavar="DIR",
        type=Path,
        default=None,
        help="Write JSON and Markdown report files into DIR",
    )
    run_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not wait for operator input; prompt steps fail instead",
    )
    run_parser.add_argument(
        "--timeout-ms",
        metavar="N",
        type=_positive_ms,
        default=None,
        help=f"Shell reply timeout in milliseconds (direct default: {DEFAULT_TIMEOUT_MS})",
    )
    run_parser.set_defaults(func=_cmd_run)

    doctor_parser = subparsers.add_parser(
        "doctor", help="Read-only camera/shell connectivity check"
    )
    doctor_parser.add_argument(
        "--backend",
        choices=BACKENDS,
        default=None,
        help=(
            "Transport backend (default: daemon on macOS/Linux, direct on "
            "Windows)"
        ),
    )
    doctor_parser.add_argument(
        "--timeout-ms",
        metavar="N",
        type=_positive_ms,
        default=None,
        help=f"Shell reply timeout in milliseconds (direct default: {DEFAULT_TIMEOUT_MS})",
    )
    doctor_parser.set_defaults(func=_cmd_doctor)

    list_parser = subparsers.add_parser(
        "list", help="List the built-in suites"
    )
    list_parser.set_defaults(func=_cmd_list)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
