#!/bin/sh
# Swap the gyro logger in over the USB shell, without a reboot.
#
# The shell's own AutoRun carries the shell.  Everything here -- the logger and
# the parking stub its writer thread needs so the code underneath it can be
# replaced -- is placed over USB, at development time.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SHELL_DIR="$HERE/../fp_usb_shell"

# The three parking words sit at +0x7C in the logger's own state block, which is
# at +0x6000 in whatever the AutoRun's `memmgr bufmem get` handed back.
PARK=$(cd "$SHELL_DIR" && python3 -c "
import sys; sys.path.insert(0,'.')
import putfile as P; print('0x%08X' % (P.mem_get(0xC3757A7C)[0] + 0x6000 + 0x7C))")

cd "$SHELL_DIR"
exec ./load.py "$HERE/logger.S" \
    --entry gyro_hook --hook 0xC00D0794 \
    --park-state "$PARK" --park-stub templates/park.S \
    --park-resume writer_resume "$@"
