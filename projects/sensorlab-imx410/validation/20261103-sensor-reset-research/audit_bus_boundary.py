"""Offline: summarize archived bus writes without importing any camera tooling.

Uses the prior independent DNG row audit for dy labels. This does not observe
sensor output, DMA completion, or the hardware's internal latching of writes.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VALIDATION = ROOT / "projects/sensorlab-imx410/validation"
BUS = VALIDATION / "20261103-first-frame-purple/bus"
AUDIT = VALIDATION / "20261103-first-frame-purple-review/row0-audit.json"
OUT = Path(__file__).with_name("bus_boundary.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(tag, dy):
    path = BUS / tag / "bus.json"
    rows = json.loads(path.read_text())
    start = next(i for i, r in enumerate(rows)
                 if r["reg"] == "0x0011" and r["val"] == "0x01")
    t0 = rows[start]["t"]
    before = {r["reg"]: r["val"] for r in rows[:start]}
    events = []
    for r in rows[start + 1:]:
        delta = (r["t"] - t0) & 0xFFFFFFFF
        if delta > 200000:
            break
        if r["reg"] in {"0x041F", "0x05E2", "0x0790", "0x0005"}:
            events.append(dict(dt_us=delta, reg=r["reg"], val=r["val"], lr=r["lr"]))
    return dict(take=tag, dy_from_prior_dng_audit=dy,
                bus_file=str(path.relative_to(ROOT)), bus_sha256=digest(path),
                last_logged_before_0011={k: before.get(k) for k in
                                        ["0x041F", "0x05E2", "0x0790"]},
                first_0011_one=rows[start], subsequent_events_200ms=events)


def main():
    labels = {r["take"]: r["dy"] for r in json.loads(AUDIT.read_text())["records"]}
    results = [summarize(tag, dy) for tag, dy in sorted(labels.items())]
    custom = [r for r in results if 2 <= int(r["take"][1:]) <= 19 or int(r["take"][1:]) >= 28]
    check = all(r["last_logged_before_0011"]["0x041F"] == "0x00" and
                r["last_logged_before_0011"]["0x05E2"] == "0x00" and
                all(e["val"] == "0x00" for e in r["subsequent_events_200ms"]
                    if e["reg"] in {"0x041F", "0x05E2"}) for r in custom)
    data = dict(scope="archived sensor command logs, no hardware execution",
                prior_row_audit=str(AUDIT.relative_to(ROOT)), prior_row_audit_sha256=digest(AUDIT),
                script_sha256=digest(Path(__file__)),
                custom_takes=len(custom), shifted_custom_takes=sum(r["dy_from_prior_dng_audit"] == 1 for r in custom),
                all_custom_041f_05e2_zero_before_and_first_200ms=check,
                all_take_register_counts={reg: dict(
                    last_logged_before_0011=dict(Counter(r["last_logged_before_0011"][reg] for r in results)),
                    writes_first_200ms=dict(Counter(e["val"] for r in results
                                                   for e in r["subsequent_events_200ms"] if e["reg"] == reg)))
                    for reg in ["0x041F", "0x05E2", "0x0790"]}, takes=results)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({k: v for k, v in data.items() if k != "takes"}, indent=2))


if __name__ == "__main__":
    main()
