#!/usr/bin/env python3
"""
Simple checker for the ARM64 benchmark artifact.
Run locally after downloading arm_real_benchmark_results.csv.
"""

import json
from pathlib import Path
import pandas as pd

csv_path = Path("arm_real_benchmark_results.csv")
json_path = Path("arm_real_benchmark_summary.json")

if not csv_path.exists():
    raise SystemExit("Missing arm_real_benchmark_results.csv in this folder.")

df = pd.read_csv(csv_path)
print("Rows:", len(df))
print("Columns:", list(df.columns))
print()
print("Architecture values:")
print(df[["machine", "uname_m", "platform"]].drop_duplicates().to_string(index=False))
print()
print("Benchmark summary:")
cols = ["path", "benchmark_type", "n", "ok", "latency_ms_mean", "latency_ms_std", "serialized_context_mb", "python_peak_mb_mean", "error"]
cols = [c for c in cols if c in df.columns]
print(df[cols].to_string(index=False))

if json_path.exists():
    print()
    print("JSON summary:")
    print(json.dumps(json.loads(json_path.read_text()), indent=2)[:2500])
