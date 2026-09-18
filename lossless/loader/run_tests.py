#!/usr/bin/env python3
"""SHA-pinned, offline-only test/compile runner. Writes only system temp files."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

PINS = {
    "seg0": (49245696, "aaa5208a028d9c4aebb9cc8614add723d456e96b2a95914f433079954320e622"),
    "page": (179725, "33946d01b1fd9bca7cba72ef55ef53e16a0469a00e5a29f35896a46e43023633"),
    "pool": (176240, "ea773283be884f8c40ca1f08d759d94157d3d58200398a92805ef3f8cd09ad96"),
}


def fingerprint(path):
    h = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            length += len(part)
            h.update(part)
    return {"length": length, "sha256": h.hexdigest()}


def checked(command):
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seg0", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True,
                        help="Exact pure-fixed-gated candidate directory")
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--nm", default="nm")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    candidate = args.candidate.resolve(strict=True)
    inputs = {"seg0": args.seg0.resolve(strict=True),
              "page": (candidate / "MainB2.fpLossless.gated.page").resolve(strict=True),
              "pool": (candidate / "MainB2.fpLossless.strings").resolve(strict=True)}
    evidence = {}
    for name, path in inputs.items():
        actual = fingerprint(path)
        if (actual["length"], actual["sha256"]) != PINS[name]:
            raise SystemExit(f"Refusing unpinned {name}: {actual}")
        evidence[name] = {"path": str(path), **actual}
    clang = shutil.which(args.clang)
    nm = shutil.which(args.nm)
    if not clang or not nm:
        raise SystemExit("clang and nm are required; no download or fallback is attempted")
    common = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
    with tempfile.TemporaryDirectory(prefix="fplossless-reader-lease-") as temp:
        temp = Path(temp)
        host = temp / "host-tests"
        arm = temp / "reader-lease-arm.o"
        checked([clang, *common, "-fsanitize=address,undefined", "-g",
                 str(here / "reader_lease.c"), str(here / "test_reader_lease.c"),
                 "-o", str(host)])
        result = json.loads(checked([str(host), *map(str, inputs.values())]))
        checked([clang, "--target=armv7-none-eabi", "-mcpu=cortex-a9", "-mthumb",
                 "-mfloat-abi=soft", "-mfpu=none",
                 "-ffreestanding", "-fno-builtin", "-O2", *common, "-c",
                 str(here / "reader_lease.c"), "-o", str(arm)])
        undefined = checked([nm, "-u", str(arm)]).strip()
        if undefined:
            raise SystemExit(f"ARM object has unresolved external calls: {undefined}")
        arm_evidence = fingerprint(arm)
        arm_evidence["undefined_symbols"] = []
    result.update({
        "kind": "offline_reader_view_lease_adapter_tests",
        "candidate_profile": "pure-fixed-gated",
        "deployable": False,
        "host_sanitizers": ["address", "undefined"],
        "arm_compile_only": arm_evidence,
        "inputs": evidence,
        "tools": {p.name: fingerprint(p) for p in
                  (here / "reader_lease.h", here / "reader_lease.c",
                   here / "test_reader_lease.c", Path(__file__).resolve())},
        "compiler": checked([clang, "--version"]).splitlines()[0],
        "gates": ["NATIVE_PAGE_SELECTOR_AND_READER_BINDING_UNIMPLEMENTED",
                  "NATIVE_PARSE_RESULT_AND_UNWIND_ABI_UNPROVEN",
                  "CACHE_FIRST_PARSE_PROVENANCE_UNIMPLEMENTED",
                  "NATIVE_ALLOCATION_AND_PARTIAL_PARSE_CLEANUP_UNPROVEN",
                  "RETAINED_STRING_AND_CALLBACK_LIFETIME_UNPROVEN",
                  "OG_HOOK_DISPATCH_NOT_MERGED",
                  "PRIVATE_VARIABLE_NAVIGATION_RENDERING_GATES_REMAIN"],
    })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
