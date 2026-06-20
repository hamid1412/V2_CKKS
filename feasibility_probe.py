#!/usr/bin/env python3
"""
Feasibility probe -- runs INSIDE a memory-capped container (docker run --memory=...).

Goal: determine, per CKKS parameter set, whether the context+Galois keys can be
built within the container's memory cap, or whether the process is OOM-killed.
A successful build prints a JSON line with the measured peak RSS; an OOM-kill is
observed by the PARENT (the workflow) as exit code 137, which the runner records.

We also run a Paillier-Add baseline to show it survives the same cap (kilobyte keys).

HONEST REPORTING: this records behavior under a stated cgroup memory cap. It is
NOT a claim about any specific physical board. The cap value is reported alongside
every outcome. If CKKS completes under the cap, that is reported as completion.
"""
import json, os, sys, time, resource, platform
import numpy as np

def peak_rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

def cgroup_limit_mb():
    # report the cap the kernel sees, so the log is self-describing
    for p in ["/sys/fs/cgroup/memory.max",                     # cgroup v2
              "/sys/fs/cgroup/memory/memory.limit_in_bytes"]:   # cgroup v1
        try:
            v = open(p).read().strip()
            if v.isdigit():
                return round(int(v) / 1e6, 1)
        except Exception:
            pass
    return None

def emit(rec):
    print(json.dumps(rec), flush=True)

TARGET = os.environ.get("PROBE", "all")   # "paillier", "ckks:N", or "all"
CAP = cgroup_limit_mb()
BASE = dict(machine=platform.machine(), python=platform.python_version(),
            cgroup_cap_mb=CAP)

def probe_paillier():
    from phe import paillier
    data = np.random.normal(0, 1, 32)
    t0 = time.perf_counter()
    pub, priv = paillier.generate_paillier_keypair(n_length=2048)
    enc = [pub.encrypt(float(v)) for v in data]; s = enc[0]
    for c in enc[1:]: s = s + c
    priv.decrypt(s)
    emit({**BASE, "scheme": "Paillier-Add-2048", "N": None,
          "latency_ms": round((time.perf_counter()-t0)*1000, 1),
          "peak_rss_mb": round(peak_rss_mb(), 1), "status": "OK"})

def probe_ckks(N, coeff):
    import tenseal as ts
    t0 = time.perf_counter()
    ctx = ts.context(ts.SCHEME_TYPE.CKKS, poly_modulus_degree=N,
                     coeff_mod_bit_sizes=coeff)
    ctx.global_scale = 2**40
    ctx.generate_galois_keys()                 # the heavy allocation
    ser = ctx.serialize(save_public_key=True, save_secret_key=False,
                        save_galois_keys=True, save_relin_keys=True)
    v = ts.ckks_vector(ctx, list(np.random.normal(0, 1, 16)))
    (v + v).decrypt()
    emit({**BASE, "scheme": "CKKS", "N": N,
          "latency_ms": round((time.perf_counter()-t0)*1000, 1),
          "serialized_mb": round(len(ser)/1e6, 2),
          "peak_rss_mb": round(peak_rss_mb(), 1), "status": "OK"})

CKKS_CFGS = {4096: [40, 20, 40], 8192: [60, 40, 40, 60],
             16384: [60, 40, 40, 40, 40, 60], 32768: [60] + [40]*8 + [60]}

if __name__ == "__main__":
    try:
        if TARGET == "paillier":
            probe_paillier()
        elif TARGET.startswith("ckks:"):
            N = int(TARGET.split(":")[1]); probe_ckks(N, CKKS_CFGS[N])
        else:
            probe_paillier()
            for N, c in CKKS_CFGS.items():
                probe_ckks(N, c)
    except MemoryError:
        emit({**BASE, "status": "PYTHON_MEMORYERROR", "target": TARGET})
        sys.exit(137)
    except Exception as e:
        emit({**BASE, "status": f"FAIL:{type(e).__name__}", "detail": str(e)[:200],
              "target": TARGET})
        sys.exit(1)
