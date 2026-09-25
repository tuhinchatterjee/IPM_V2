"""
Resource sampling with its measurement source attached (M14).

What is measured is what is reported: the lab process's resident memory and,
on Linux, system available memory from /proc/meminfo. GPU metrics are never
invented; a local runtime's own memory (e.g. Ollama's loaded-model size) is
reported by its adapter when the runtime exposes it. On Apple silicon the
memory is unified -- it is never reported as CPU RAM plus GPU VRAM.
"""

from __future__ import annotations

import os
import platform
import resource
import threading
import time
from typing import Any


def _rss_mb() -> float | None:
    try:
        with open(f"/proc/{os.getpid()}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return None


def _mem_available_mb() -> float | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except OSError:
        pass
    return None


def host_facts() -> dict[str, Any]:
    total = None
    try:
        with open("/proc/meminfo") as f:
            total = int(f.readline().split()[1]) / 1024.0
    except OSError:
        pass
    return {"system": platform.system(), "machine": platform.machine(),
            "processor": platform.processor(), "cpus": os.cpu_count(),
            "memory_total_mb": total,
            "memory_semantics": ("unified (Apple silicon)" if
                                 platform.system() == "Darwin" and
                                 platform.machine() == "arm64" else
                                 "host RAM"),
            "gpu": None, "gpu_reason": "not measured by the lab sampler"}


class Sampler:
    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._samples: list[dict[str, Any]] = []
        self._t: threading.Thread | None = None
        self._started = 0.0

    def _loop(self) -> None:
        while True:
            self._samples.append({"t_ms": (time.monotonic() - self._started)
                                  * 1000, "lab_rss_mb": _rss_mb(),
                                  "system_available_mb":
                                  _mem_available_mb()})
            if self._stop.wait(self.interval_s):
                return

    def start(self) -> None:
        self._started = time.monotonic()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._t:
            self._t.join(2)
        rss = [s["lab_rss_mb"] for s in self._samples
               if s["lab_rss_mb"] is not None]
        avail = [s["system_available_mb"] for s in self._samples
                 if s["system_available_mb"] is not None]
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports KiB, macOS bytes.
        maxrss_mb = maxrss / 1024.0 if platform.system() != "Darwin" \
            else maxrss / (1024.0 * 1024.0)
        return {
            "method": "lab process /proc/<pid>/status VmRSS and "
                      "/proc/meminfo MemAvailable, sampled",
            "interval_s": self.interval_s, "n": len(self._samples),
            "peak_lab_rss_mb": max(rss) if rss else None,
            "peak_lab_rss_status": "MEASURED" if rss else "UNAVAILABLE",
            "min_system_available_mb": min(avail) if avail else None,
            "min_system_available_status": ("MEASURED" if avail else
                                            "UNAVAILABLE"),
            "process_maxrss_mb": maxrss_mb,
            "process_maxrss_note": "whole lab process lifetime, not this "
                                   "child alone",
            "model_runtime_memory": None,
            "model_runtime_memory_reason": (
                "reported by the adapter when the runtime exposes it "
                "(e.g. Ollama /api/ps); the lab sampler cannot see another "
                "process's GPU/unified allocation"),
            "gpu": None, "gpu_reason": "not measured",
            "host": host_facts(), "samples": self._samples[:600]}
