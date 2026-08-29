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
./load.py "$HERE/logger.S" \
    --entry gyro_hook --hook 0xC00D0794 \
    --park-state "$PARK" --park-stub templates/park.S \
    --park-resume writer_resume "$@"

# The Gyroflow lens profile, as text, in the twelve kilobytes at the top of the
# pool.  The camera copies it beside every clip whose mode matches; it is data,
# not code, because a profile depends on the lens and the mode and on nothing
# else, and formatting decimals in ARM to rebuild it each time would be work for
# no gain.  Not fatal if it fails -- takes still get their .GYR and .CSV.
python3 "$HERE/putprofile.py" || echo "  (no profile placed; clips will have no .JSON)"

