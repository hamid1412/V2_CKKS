#!/usr/bin/env python3
"""
Native ARM64 HE microbenchmark for reviewer-response validation.

Outputs:
  - arm_real_benchmark_results.csv
  - arm_real_benchmark_summary.json

What it measures:
  1) Platform metadata: architecture, CPU, RAM.
  2) Paillier-2048 add pipeline latency.
  3) CKKS context/key serialized size and CKKS vector-add latency if TenSEAL is available.

Important:
  This is an architecture-level ARM64 validation, not board-level Raspberry Pi/Jetson energy profiling.
"""

import csv
import json
import time
import platform
import statistics
import tracemalloc
import subprocess
from datetime import datetime

import numpy as np

try:
    from phe import paillier
    PHE_AVAILABLE = True
    PHE_IMPORT_ERROR = ""
except Exception as e:
    PHE_AVAILABLE = False
    PHE_IMPORT_ERROR = repr(e)

try:
    import tenseal as ts
    TENSEAL_AVAILABLE = True
    TENSEAL_IMPORT_ERROR = ""
except Exception as e:
    TENSEAL_AVAILABLE = False
    TENSEAL_IMPORT_ERROR = repr(e)

OUT_CSV = "arm_real_benchmark_results.csv"
OUT_JSON = "arm_real_benchmark_summary.json"


def utc_now():
    return datetime.utcnow().isoformat() + "Z"


def safe_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT).strip()
    except Exception as e:
        return f"ERROR: {repr(e)}"


def get_meminfo_mb():
    mem = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = float(v.strip().split()[0]) / 1024.0
    except Exception:
        pass
    return {
        "mem_total_mb": mem.get("MemTotal", np.nan),
        "mem_available_mb": mem.get("MemAvailable", np.nan),
    }


def metadata():
    d = {
        "timestamp_utc": utc_now(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "uname_m": safe_cmd("uname -m"),
        "uname_a": safe_cmd("uname -a"),
        "lscpu_first_lines": "\\n".join(safe_cmd("lscpu").splitlines()[:12]),
        "phe_available": PHE_AVAILABLE,
        "phe_import_error": PHE_IMPORT_ERROR,
        "tenseal_available": TENSEAL_AVAILABLE,
        "tenseal_import_error": TENSEAL_IMPORT_ERROR,
    }
    d.update(get_meminfo_mb())
    return d


def time_fn(fn, reps=3):
    vals_ms = []
    peaks_mb = []
    errors = []
    for _ in range(reps):
        tracemalloc.start()
        t0 = time.perf_counter()
        try:
            fn()
            ok = True
        except Exception as e:
            ok = False
            errors.append(repr(e))
        dt_ms = (time.perf_counter() - t0) * 1000.0
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        vals_ms.append(dt_ms)
        peaks_mb.append(peak / (1024 * 1024))
        if not ok:
            break
    return {
        "ok": len(errors) == 0,
        "error": "; ".join(errors),
        "reps_completed": len(vals_ms),
        "latency_ms_mean": statistics.mean(vals_ms) if vals_ms else np.nan,
        "latency_ms_std": statistics.stdev(vals_ms) if len(vals_ms) > 1 else 0.0,
        "python_peak_mb_mean": statistics.mean(peaks_mb) if peaks_mb else np.nan,
    }


def paillier_add_bench(n, bits=2048, reps=3):
    if not PHE_AVAILABLE:
        return {"ok": False, "error": PHE_IMPORT_ERROR, "reps_completed": 0}

    # Generate the key outside the timed section because this benchmark is for operation latency.
    pub, priv = paillier.generate_paillier_keypair(n_length=bits)
    x = [float(i % 10) for i in range(n)]

    def run():
        enc = [pub.encrypt(v) for v in x]
        s = enc[0]
        for c in enc[1:]:
            s = s + c
        out = priv.decrypt(s)
        expected = sum(x)
        if abs(out - expected) > 1e-6:
            raise RuntimeError(f"Paillier wrong result: got {out}, expected {expected}")

    return time_fn(run, reps=reps)


def make_ckks_context(poly_mod_degree, coeff_mod_bit_sizes):
    ctx = ts.context(
        ts.SCHEME_TYPE.CKKS,
        poly_modulus_degree=poly_mod_degree,
        coeff_mod_bit_sizes=coeff_mod_bit_sizes,
    )
    ctx.global_scale = 2 ** min(40, max(20, min(coeff_mod_bit_sizes) - 1))
    ctx.generate_galois_keys()
    try:
        ctx.generate_relin_keys()
    except Exception:
        pass
    return ctx


def ckks_context_memory(profile_name, poly_mod_degree, coeffs):
    if not TENSEAL_AVAILABLE:
        return {"ok": False, "error": TENSEAL_IMPORT_ERROR, "reps_completed": 0}

    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        ctx = make_ckks_context(poly_mod_degree, coeffs)
        serialized = ctx.serialize(
            save_public_key=True,
            save_secret_key=True,
            save_galois_keys=True,
            save_relin_keys=True,
        )
        ok = True
        err = ""
        size_mb = len(serialized) / (1024 * 1024)
    except Exception as e:
        ok = False
        err = repr(e)
        size_mb = np.nan
    dt_ms = (time.perf_counter() - t0) * 1000.0
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "ok": ok,
        "error": err,
        "reps_completed": 1,
        "latency_ms_mean": dt_ms,
        "latency_ms_std": 0.0,
        "serialized_context_mb": size_mb,
        "python_peak_mb_mean": peak / (1024 * 1024),
    }


def ckks_vector_add_bench(n, poly_mod_degree, coeffs, reps=3):
    if not TENSEAL_AVAILABLE:
        return {"ok": False, "error": TENSEAL_IMPORT_ERROR, "reps_completed": 0}

    ctx = make_ckks_context(poly_mod_degree, coeffs)
    x = [float(i % 10) for i in range(n)]
    y = [float((i + 1) % 10) for i in range(n)]

    def run():
        vx = ts.ckks_vector(ctx, x)
        vy = ts.ckks_vector(ctx, y)
        vz = vx + vy
        out = vz.decrypt()
        if len(out) != n:
            raise RuntimeError(f"CKKS length mismatch: got {len(out)}, expected {n}")

    return time_fn(run, reps=reps)


def main():
    meta = metadata()
    rows = []

    print("=== PLATFORM ===")
    print(json.dumps(meta, indent=2)[:3000])
    print()

    for n in [8, 32, 128]:
        print(f"Running Paillier-Add-2048, n={n}")
        r = paillier_add_bench(n=n, bits=2048, reps=3)
        rows.append({
            **meta,
            "path": "Paillier-Add-2048",
            "benchmark_type": "operation",
            "n": n,
            "poly_degree": "",
            "coeff_mod_bit_sizes": "",
            "serialized_context_mb": "",
            **r,
        })

    ckks_profiles = [
        ("CKKS-4096-low", 4096, [40, 20, 40]),
        ("CKKS-8192-mid", 8192, [60, 40, 40, 60]),
    ]

    for name, degree, coeffs in ckks_profiles:
        print(f"Measuring {name} context/key serialized footprint")
        r = ckks_context_memory(name, degree, coeffs)
        rows.append({
            **meta,
            "path": name,
            "benchmark_type": "context_memory",
            "n": 0,
            "poly_degree": degree,
            "coeff_mod_bit_sizes": str(coeffs),
            **r,
        })

        for n in [8, 32, 128]:
            print(f"Running {name} vector add, n={n}")
            r = ckks_vector_add_bench(n=n, poly_mod_degree=degree, coeffs=coeffs, reps=3)
            rows.append({
                **meta,
                "path": name,
                "benchmark_type": "operation",
                "n": n,
                "poly_degree": degree,
                "coeff_mod_bit_sizes": str(coeffs),
                "serialized_context_mb": "",
                **r,
            })

    keys = sorted(set(k for row in rows for k in row.keys()))
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "created_utc": utc_now(),
        "is_arm64": str(meta.get("machine", "")).lower() in ["aarch64", "arm64"] or str(meta.get("uname_m", "")).lower() in ["aarch64", "arm64"],
        "platform": meta,
        "n_rows": len(rows),
        "all_rows_ok": all(bool(r.get("ok")) for r in rows),
        "tenseal_available": TENSEAL_AVAILABLE,
        "phe_available": PHE_AVAILABLE,
        "csv": OUT_CSV,
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print()
    print(f"Saved {OUT_CSV}")
    print(f"Saved {OUT_JSON}")
    print("Summary:")
    print(json.dumps(summary, indent=2)[:3000])


if __name__ == "__main__":
    main()
