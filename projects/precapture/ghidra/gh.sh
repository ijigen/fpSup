#!/bin/bash
# Run one of the scripts here against the precapture copy of the fp-dfd project.
#   ./gh.sh Decomp /tmp/out.c C037E0F8 C0377A30
#   ./gh.sh Xrefs  /tmp/x.txt C0B9B150
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
project_dir="${PRECAP_GHIDRA:-/opt/sigma/precap-ghidra}"
script="$1"; shift
/opt/ghidra_12.1.4_PUBLIC/support/analyzeHeadless "$project_dir" fpdfd \
  -process MAIN_c0000000.bin -noanalysis -readOnly \
  -scriptPath "$here" -postScript "$script.java" "$@" 2>&1 \
  | grep -E "ERROR|Exception|SCRIPT" | grep -v "^INFO" || true
