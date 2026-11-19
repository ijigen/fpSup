# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-in-the-loop test harness for SIGMA fp SUP cards.

The package is split into small pieces:

* :mod:`fpautotest.session` -- transport backends (``fpshd`` daemon or direct
  pyusb) and their common shell surface.
* :mod:`fpautotest.plan` -- suite loading/validation.
* :mod:`fpautotest.steps` -- one step executor.
* :mod:`fpautotest.runner` -- suite orchestration and reports.
* :mod:`fpautotest.cli` -- the ``python -m fpautotest`` command line.

Nothing here imports ``fp_companion`` or any application code; the only
camera-facing dependency is the upstream ``fp_usb_shell`` directory.
"""

from __future__ import annotations

from .plan import VALID_STEP_KINDS, Step, Suite, load_suite
from .runner import RunResult, StepResult, run_suite
from .session import (
    BACKENDS,
    DaemonSession,
    DirectSession,
    ShellError,
    default_backend,
    open_session,
)
from .steps import execute

__all__ = [
    "BACKENDS",
    "VALID_STEP_KINDS",
    "DaemonSession",
    "DirectSession",
    "RunResult",
    "ShellError",
    "Step",
    "StepResult",
    "Suite",
    "default_backend",
    "execute",
    "load_suite",
    "open_session",
    "run_suite",
]

__version__ = "0.1.0"
