# ARM64 CKKS Feasibility Sweep (option 2)

Real-hardware evidence for the manuscript's **feasibility** claim: on a constrained
memory budget the high-security CKKS context cannot be built, while Paillier
(kilobyte keys) still runs. Runs on **GitHub-hosted ARM64** runners — no physical
Pi/Jetson required — by building TenSEAL from source in an `arm64v8` container and
running a probe under several `docker run --memory` caps.

## Files
- `Dockerfile.arm64` — arm64 Python 3.11 image; **builds TenSEAL from source**
  (fixes the missing aarch64 pip wheel), sanity-checks CKKS at build time.
- `feasibility_probe.py` — runs inside the capped container; per CKKS parameter set,
  builds context+Galois keys and reports peak RSS, or is OOM-killed (exit 137).
  Also runs a Paillier-Add baseline that must survive the tightest cap.
- `.github/workflows/arm-feasibility.yml` — builds the image and sweeps caps
  {256,350,512,1024,2048} MB x N {4096,8192,16384}; uploads artifacts.
- `integrate_feasibility.py` — turns artifacts into `feasibility_table.csv`,
  `arm_costmodel_anchor.csv`, and a drop-in `manuscript_feasibility.tex`.
- (kept) `arm_benchmark.py`, `.github/workflows/arm-benchmark.yml`,
  `integrate_arm_results.py` — native ARM Paillier microbenchmark from run 1.

## Run it
1. Push these files to a GitHub repo.
2. Actions -> "ARM64 CKKS Feasibility Sweep (option 2)" -> Run workflow.
3. Download the `arm64-feasibility-results` artifact.
4. `python integrate_feasibility.py` -> feasibility table + LaTeX snippet.

## Read it honestly
- `OK`  = CKKS context completed under that memory cap.
- `OOM` = container killed under the cap (exit 137); CKKS infeasible there.
- The cap value is reported with every outcome. If CKKS completes at 350 MB, the
  paper must say so (which would weaken the feasibility claim). We report whatever
  the sweep shows.

## Runner note
GitHub ARM64 runners are ~16 GB Neoverse servers. The **memory cap**, not host RAM,
creates the constrained condition; report as "behavior under an N-MB cgroup cap on
ARM64," not as a named board. For a specific board profile, run
`feasibility_probe.py` directly on the Pi/Jetson.
