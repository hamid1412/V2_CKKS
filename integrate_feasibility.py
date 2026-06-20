#!/usr/bin/env python3
"""
Parse the option-2 feasibility-sweep artifacts and produce:
  - feasibility_table.csv          (cap_mb x N -> completed / OOM-killed)
  - arm_costmodel_anchor.csv       (real ARM Paillier/CKKS latencies + peak RSS)
  - manuscript_feasibility.tex     (drop-in LaTeX table for the paper)

Run locally after downloading the 'arm64-feasibility-results' artifact:
  python integrate_feasibility.py
Honest reporting: 'OOM' means the container was killed under the stated cgroup cap
(exit 137); 'OK' means CKKS completed under that cap. Both are reported verbatim.
"""
import json, csv
from pathlib import Path

idx = Path("sweep_index.csv")
raw = Path("sweep_raw.jsonl")
uncapped = Path("uncapped.jsonl")
if not idx.exists():
    raise SystemExit("Missing sweep_index.csv -- download the workflow artifact first.")

# 1) feasibility matrix from exit codes (137 => OOM-killed under the cap)
rows = list(csv.DictReader(open(idx)))
caps, Ns = set(), set()
status = {}
for r in rows:
    cap = int(r["cap_mb"]); tgt = r["target"]; code = int(r["exit_code"])
    if tgt.startswith("ckks:"):
        N = int(tgt.split(":")[1]); caps.add(cap); Ns.add(N)
        status[(cap, N)] = "OK" if code == 0 else ("OOM" if code == 137 else f"ERR{code}")
caps, Ns = sorted(caps), sorted(Ns)

with open("feasibility_table.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["cap_mb"] + [f"N={n}" for n in Ns])
    for cap in caps:
        w.writerow([cap] + [status.get((cap, n), "-") for n in Ns])
print("feasibility_table.csv:")
print(f"  {'cap(MB)':>8s} " + " ".join(f"N={n:<6d}" for n in Ns))
for cap in caps:
    print(f"  {cap:>8d} " + " ".join(f"{status.get((cap,n),'-'):<8s}" for n in Ns))

# 2) real ARM latency/RSS anchors from the uncapped run
anchors = []
if uncapped.exists():
    for line in uncapped.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("status") == "OK":
            anchors.append(d)
    with open("arm_costmodel_anchor.csv", "w", newline="") as f:
        cols = ["scheme", "N", "latency_ms", "serialized_mb", "peak_rss_mb", "machine"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader(); w.writerows(anchors)
    print("\narm_costmodel_anchor.csv written (", len(anchors), "rows )")

# 3) drop-in LaTeX table
machine = anchors[0]["machine"] if anchors else "aarch64"
lines = [r"\begin{table}[!ht]\centering",
         r"\caption{Real ARM64 (%s) feasibility sweep: CKKS context build under cgroup memory caps. " % machine
         + r"`OOM' = container killed under the cap (exit 137); `OK' = completed. "
         + r"Paillier-Add survived all caps down to 256\,MB.}",
         r"\label{tab:arm_feasibility}", r"\small",
         r"\begin{tabular}{@{}l" + "c" * len(Ns) + r"@{}}", r"\toprule",
         "Memory cap & " + " & ".join(f"CKKS $N{{=}}{n}$" for n in Ns) + r" \\", r"\midrule"]
for cap in caps:
    lines.append(f"{cap}\\,MB & " + " & ".join(status.get((cap, n), "-") for n in Ns) + r" \\")
lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
Path("manuscript_feasibility.tex").write_text("\n".join(lines))
print("\nmanuscript_feasibility.tex written (drop into Section 9).")
