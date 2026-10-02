#!/usr/bin/env python3
"""
Hardware identity and hardware-specific A40-style fit for the RunPod lab.

    python hardware.py detect [--runtime-dir DIR]     # nvidia-smi -> record

The fit methodology is unchanged from the A40 work: weights + KV cache at
the configured context + a fixed runtime overhead must stay within a
conservative usable fraction of GPU memory. Only the memory figure changes
with the hardware, and every result is labelled with the hardware it was
computed for:

  A40_48GB                      historical benchmark hardware (nominal 48 GB,
                                fit-v1); evidence recorded there is never
                                overwritten or reinterpreted
  RTX_PRO_6000_BLACKWELL_96GB   the current RunPod host (detected VRAM)
  <GPU>_<N>GB                   any future host, from its detected VRAM

The CURRENT host decides probe eligibility; historical results stay as
evidence. The current host is the record the bootstrap persisted at
<runtime>/hardware/CURRENT_HOST.json -- never a live nvidia-smi read inside
the pin step, so tests and other machines are never altered by the GPU
they happen to run on. Without a record the historical A40 assumption is
used and labelled as an assumption. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

USABLE_FRACTION = 0.90          # same conservative fraction as the A40 fit
OVERHEAD_GB = 3.0               # CUDA context, graphs, activations
FIT_METHOD = ("fit-v2: weights + KV cache (configured context, 2-byte KV) + "
              f"{OVERHEAD_GB} GB overhead <= {USABLE_FRACTION:.0%} of GPU "
              "memory")
A40_ID = "A40_48GB"
#: The historical benchmark hardware exactly as its evidence was computed.
HISTORICAL_A40 = {
    "hardware_id": A40_ID, "gpu": "NVIDIA A40", "vram_gb_for_fit": 48.0,
    "memory_total_mib": None, "usable_fraction": USABLE_FRACTION,
    "usable_budget_gb": round(48.0 * USABLE_FRACTION, 2),
    "fit_method": "fit-v1: nominal 48 GB x 0.90 (historical A40 benchmark)",
    "driver_version": None, "host_cuda": None, "source": "historical",
}
#: Known accelerators: name pattern -> hardware id (marketed memory class).
KNOWN = ((r"\bA40\b", A40_ID),
         (r"RTX PRO 6000 Blackwell", "RTX_PRO_6000_BLACKWELL_96GB"),
         (r"\bH100\b.*80", "H100_80GB"), (r"\bA100\b.*80", "A100_80GB"),
         (r"\bL40S\b", "L40S_48GB"))


def hardware_id(gpu: str | None, memory_total_mib: int | None) -> str:
    for pat, hid in KNOWN:
        if gpu and re.search(pat, gpu, re.I):
            return hid
    slug = re.sub(r"[^A-Z0-9]+", "_", (gpu or "UNKNOWN_GPU").upper()).strip(
        "_").replace("NVIDIA_", "")
    gib = round((memory_total_mib or 0) / 1024)
    return f"{slug}_{gib}GB"


def status_label(hid: str, fits: bool) -> str:
    """FITS_/RESOURCE_BLOCKED_ + hardware. The A40 keeps its historical
    labels (FITS_A40 / RESOURCE_BLOCKED_A40) so its evidence reads the
    same as before."""
    tag = "A40" if hid == A40_ID else hid
    return f"{'FITS' if fits else 'RESOURCE_BLOCKED'}_{tag}"


def from_host(host: dict[str, Any]) -> dict[str, Any]:
    """A record from vllm_runtime.parse_nvidia_smi() output."""
    mib = None
    m = re.search(r"(\d+)", str(host.get("gpu_memory") or ""))
    if m:
        mib = int(m.group(1))
    vram_gb = round(mib * 1048576 / 1e9, 2) if mib else None
    return {
        "hardware_id": hardware_id(host.get("gpu"), mib),
        "gpu": host.get("gpu"), "gpu_count": host.get("gpu_count"),
        "memory_total_mib": mib, "vram_gb_for_fit": vram_gb,
        "usable_fraction": USABLE_FRACTION,
        "usable_budget_gb": round(vram_gb * USABLE_FRACTION, 2)
        if vram_gb else None,
        "driver_version": host.get("driver_version"),
        "host_cuda": host.get("host_cuda"), "fit_method": FIT_METHOD,
        "source": "detected (nvidia-smi)",
        "detected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def current_path(runtime: Path) -> Path:
    return runtime / "hardware" / "CURRENT_HOST.json"


def save_current(runtime: Path, rec: dict[str, Any]) -> Path:
    """CURRENT_HOST.json plus an append-only history entry per detection."""
    d = runtime / "hardware"
    (d / "history").mkdir(parents=True, exist_ok=True)
    stamp = rec.get("detected_at", "").replace(":", "")
    hist = d / "history" / f"{stamp}_{rec['hardware_id']}.json"
    hist.write_text(json.dumps(rec, indent=1, sort_keys=True))
    tmp = d / ".CURRENT_HOST.json.part"
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True))
    os.replace(tmp, current_path(runtime))     # no chmod (geesefs)
    return current_path(runtime)


def current(runtime: Path | None) -> dict[str, Any]:
    if runtime is not None and current_path(runtime).exists():
        rec = json.loads(current_path(runtime).read_text())
        if rec.get("vram_gb_for_fit"):
            return rec
    return HISTORICAL_A40 | {"assumed": True,
                             "note": "no detected host recorded in this "
                                     "runtime: historical A40 assumption"}


def fit(p: dict[str, Any], *, context: int, max_output: int,
        hw: dict[str, Any] | None = None, kv_bytes: int = 2
        ) -> dict[str, Any]:
    """The A40 methodology against `hw` (default: the historical A40)."""
    hw = hw or HISTORICAL_A40
    c = p.get("config") or {}
    layers = c.get("num_hidden_layers") or 0
    heads = c.get("num_attention_heads") or 0
    kv_heads = c.get("num_key_value_heads") or heads
    head_dim = c.get("head_dim") or ((c.get("hidden_size") or 0) //
                                     max(1, heads))
    native = p.get("native_context") or context
    ctx = min(context, native)
    per_token = 2 * layers * kv_heads * head_dim * kv_bytes
    weights_gb = (p.get("weights_bytes") or 0) / 1e9
    kv_gb = per_token * ctx / 1e9
    total = weights_gb + kv_gb + OVERHEAD_GB
    vram = float(hw["vram_gb_for_fit"])
    budget = vram * USABLE_FRACTION
    known = bool(layers and kv_heads and head_dim and p.get("weights_bytes"))
    ok = known and total <= budget and max_output < ctx
    return {"weights_gb": round(weights_gb, 2), "kv_cache_gb": round(kv_gb, 2),
            "kv_bytes_per_token": per_token, "context": ctx,
            "native_context": native, "output_reservation": max_output,
            "runtime_overhead_gb": OVERHEAD_GB,
            "total_gb": round(total, 2), "budget_gb": round(budget, 2),
            "fits": ok, "computable": known,
            "hardware_id": hw["hardware_id"], "gpu": hw.get("gpu"),
            "vram_gb": vram, "fit_method": hw.get("fit_method"),
            "resource_status": (status_label(hw["hardware_id"], ok)
                                if known else "FIT_NOT_COMPUTED"),
            "summary": (f"{hw['hardware_id']}: weights {weights_gb:.1f} GB + "
                        f"KV {kv_gb:.1f} GB ({ctx} tokens) + overhead "
                        f"{OVERHEAD_GB} GB = {total:.1f} GB vs "
                        f"{budget:.1f} GB usable")
            if known else "config.json/weights incomplete: fit not computed"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("command", choices=("detect", "show"))
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", ""))
    args = ap.parse_args(argv)
    runtime = Path(args.runtime_dir) if args.runtime_dir else None
    if args.command == "show":
        print(json.dumps(current(runtime), indent=1))
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import vllm_runtime as vr
    rec = from_host(vr.read_host())
    if not rec["memory_total_mib"]:
        print("HARDWARE_NOT_DETECTED: nvidia-smi reported no GPU memory")
        return 12
    if runtime is not None:
        save_current(runtime, rec)
    print(f"gpu: {rec['gpu']} (x{rec['gpu_count']})")
    print(f"hardware_id: {rec['hardware_id']}")
    print(f"vram: {rec['memory_total_mib']} MiB = {rec['vram_gb_for_fit']} GB;"
          f" usable budget {rec['usable_budget_gb']} GB "
          f"({USABLE_FRACTION:.0%})")
    print(f"driver: {rec['driver_version']}  cuda: {rec['host_cuda']}")
    print(f"fit_method: {rec['fit_method']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
