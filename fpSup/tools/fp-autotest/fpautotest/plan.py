# SPDX-License-Identifier: GPL-3.0-or-later
"""Suite definitions and loaders for the fpSup hardware test harness.

A suite file looks like this (YAML or JSON)::

    name: lexpo-smoke
    description: Read-only checks for the LExpo patch
    steps:
      - kind: shell
        params:
          command: version
          expect_regex: 'fp'
      - kind: mem_expect
        params:
          addr: 0xC007F324
          value: 0xE309C6FC

For convenience the step parameters may also be written inline::

      - kind: shell
        command: version

JSON is supported without any third-party package.  YAML needs PyYAML; when it
is missing the loader raises a clear :class:`ValueError` rather than failing
with a bare ``ImportError``.  YAML parses ``0x...`` scalars as integers already;
string forms are accepted too so JSON and hand-written suites behave the same
way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

VALID_STEP_KINDS = frozenset(
    {
        "shell",
        "mem_expect",
        "mem_expect_any",
        "status_expect",
        "prompt",
        "wait",
    }
)

YAML_SUFFIXES = (".yaml", ".yml")


@dataclass
class Step:
    kind: str
    params: dict = field(default_factory=dict)


@dataclass
class Suite:
    name: str
    description: str
    steps: list[Step] = field(default_factory=list)


def _coerce_step(raw: object, position: int) -> Step:
    if not isinstance(raw, dict):
        raise ValueError(f"step {position}: expected a mapping, got {type(raw).__name__}")

    kind = raw.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError(f"step {position}: missing or invalid 'kind'")
    kind = kind.strip()
    if kind not in VALID_STEP_KINDS:
        allowed = ", ".join(sorted(VALID_STEP_KINDS))
        raise ValueError(f"step {position}: unknown kind {kind!r} (allowed: {allowed})")

    nested = raw.get("params", {})
    if nested is None:
        nested = {}
    if not isinstance(nested, dict):
        raise ValueError(f"step {position}: 'params' must be a mapping")

    # Allow inline params alongside kind/params; explicit params win.
    inline = {key: value for key, value in raw.items() if key not in ("kind", "params")}
    params = dict(inline)
    params.update(nested)
    return Step(kind=kind, params=params)


def _coerce_suite(raw: object, source: str) -> Suite:
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: suite root must be a mapping")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{source}: missing or invalid 'name'")

    description = raw.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError(f"{source}: 'description' must be a string")

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError(f"{source}: 'steps' must be a list")

    steps = [_coerce_step(item, index) for index, item in enumerate(raw_steps, 1)]
    return Suite(name=name.strip(), description=description, steps=steps)


def _load_yaml(target: Path) -> object:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(
            f"{target}: PyYAML is required to load YAML suites. Install it with "
            "`python -m pip install pyyaml`, or write the suite as .json."
        ) from exc
    with target.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_suite(path: str | Path) -> Suite:
    """Load and validate a suite from ``.yaml``/``.yml`` or ``.json``.

    Raises :class:`ValueError` for malformed files, unknown step kinds, or a
    YAML suite when PyYAML is not installed.
    """
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix in YAML_SUFFIXES:
        raw = _load_yaml(target)
    elif suffix == ".json":
        with target.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    else:
        raise ValueError(f"unsupported suite extension {suffix!r}: {target}")

    if raw is None:
        raise ValueError(f"{target}: suite is empty")
    return _coerce_suite(raw, str(target))
