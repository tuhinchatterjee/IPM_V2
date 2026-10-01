#!/usr/bin/env python3
"""
vLLM runtime layer for the RunPod A40 benchmark: host/driver gate, exact
environment provenance, parser-registry verification and model-import
preflight. Sends nothing to any model; never calls a paid API.

    python vllm_runtime.py host        [--runtime-dir DIR]   # exit 7 if blocked
    python vllm_runtime.py fetch-wheel --dest DIR             # verified wheel
    python vllm_runtime.py preflight   --venv-python PY [--runtime-dir DIR]
    python vllm_runtime.py show        [--runtime-dir DIR]   # read-only

HOST GATE (before vLLM is installed or any model is served). vLLM 0.30.0's
standard PyPI wheel pins torch==2.13.0, whose PyPI build depends on
cuda-toolkit 13.0.3: a CUDA 13.0 runtime. NVIDIA's CUDA 13.0 GA release
requires Linux driver >= 580.65.06 (CUDA Toolkit release notes, driver
table). A host below that is VLLM_HOST_DRIVER_INCOMPATIBLE and the run stops
before any probe. Nothing is worked around: no CUDA compatibility package,
no driver change, no other vLLM build, no other engine. Remedy: redeploy
the Pod on a host with a compatible driver. The preflight additionally
initialises CUDA from the installed torch (no model), which is the
empirical proof on the actual host.

ENVIRONMENT. One Pod-local vLLM venv for every model: Python 3.12, the
sha256-verified vllm 0.30.0 wheel, and vllm-0.30.0-constraints.txt (the
dependency set vLLM's own CI locked for cu130 / Python 3.12). The exact
installed versions, wheel identity, torch CUDA build and the verdict are
written to <runtime>/vllm_runtime/RUNTIME_MANIFEST.json on the persistent
volume.

PARSERS. Tool/reasoning parser names are taken from the INSTALLED vLLM's
ToolParserManager / ReasoningParserManager and each assigned parser class
is loaded; an unregistered name is TOOL_PARSER_MISSING. A parser is still
only a candidate until the harmless READY_E2E capability probe passes.

IMPORTS. Each pinned architecture's vLLM model module is imported (no
weights, no GPU allocation) so an incompatible Transformers is caught as
TRANSFORMERS_INCOMPATIBLE before any download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONSTRAINTS = HERE / "vllm-0.30.0-constraints.txt"

VLLM_VERSION = "0.30.0"
VLLM_CUDA = "13.0"
WHEEL = {
    "filename": "vllm-0.30.0-cp38-abi3-manylinux_2_28_x86_64.whl",
    "sha256": "ef52ee58c410ead0b8afb190838fa4cbcb52075596f67862a03859d984966ac4",
    "url": "https://files.pythonhosted.org/packages/1a/25/f5087a8f382e197a"
           "73672768b389d020b9d92e38371c3b0fc6dd883bbb34/vllm-0.30.0-cp38-"
           "abi3-manylinux_2_28_x86_64.whl",
    "source": "PyPI vllm 0.30.0 (uploaded 2026-09-22), standard CUDA build",
}
PYTHON = "3.12"
#: Expected installed versions (vLLM v0.30.0 requirements/test/cuda.txt).
LOCK = {"vllm": "0.30.0", "torch": "2.13.0", "transformers": "5.16.1",
        "tokenizers": "0.23.1", "huggingface-hub": "1.31.0",
        "mistral-common": "1.11.6", "xgrammar": "0.2.3",
        "safetensors": "0.8.0", "torchvision": "0.28.0",
        "torchaudio": "2.11.0"}
LOCK_SOURCE = ("vLLM v0.30.0 requirements/test/cuda.txt (uv pip compile "
               "--torch-backend cu130 --python-version 3.12); torch 2.13.0 "
               "on PyPI requires cuda-toolkit==13.0.3")
#: Minimum Linux driver per CUDA runtime (NVIDIA CUDA Toolkit release notes).
DRIVER_MIN = {"13.0": "580.65.06"}
DRIVER_SOURCE = ("NVIDIA CUDA Toolkit release notes, CUDA Toolkit and "
                 "Corresponding Driver Versions: CUDA 13.0 GA >= 580.65.06 "
                 "(Linux)")
REMEDIATION = ("redeploy the Pod on a RunPod host with a compatible driver "
               "(NVIDIA Linux driver >= 580.65.06); do not install CUDA "
               "compatibility packages, change the driver, downgrade vLLM "
               "or switch engines -- the benchmark must be reproducible")

#: Tool / reasoning parsers registered in vLLM v0.30.0 (vllm/tool_parsers/
#: __init__.py, vllm/reasoning/__init__.py). Planning only: the probe path
#: requires the list read from the INSTALLED vLLM.
STATIC_TOOL_PARSERS = (
    "apertus", "cohere_command3", "cohere_command4", "deepseek_v3",
    "deepseek_v31", "deepseek_v32", "deepseek_v4", "deepseek_v41", "dots",
    "ernie45", "functiongemma", "gemma4", "gigachat3", "glm45", "glm47",
    "granite", "granite-20b-fc", "granite4", "hermes", "hunyuan_a13b",
    "hy_v3", "hy_v4", "inkling", "internlm", "jamba", "k2_horizon",
    "kimi_k2", "kimi_k3", "lfm2", "ling3", "llama3_json", "llama4_json",
    "llama4_pythonic", "longcat", "mimo", "minicpm5", "minimax_m2",
    "minimax_m3", "mistral", "muse_glimmer", "olmo3", "openai",
    "phi4_mini_json", "poolside_v1", "pythonic", "qwen3_coder", "qwen3_xml",
    "seed_oss", "step3", "step3p5", "xlam")
STATIC_REASONING_PARSERS = (
    "cohere_command3", "cohere_command4", "deepseek_r1", "deepseek_v3",
    "deepseek_v4", "deepseek_v41", "ernie45", "gemma4", "glm45", "glm47",
    "granite", "holo2", "hunyuan_a13b", "hy_v3", "hy_v4", "inkling",
    "k2_horizon", "kimi_k2", "kimi_k3", "ling3", "mimo", "minimax_m2",
    "minimax_m2_append_think", "minimax_m3", "mistral", "muse_glimmer",
    "nemotron_v3", "olmo3", "openai_gptoss", "poolside_v1", "qwen3",
    "seed_oss", "step3", "step3p5")

#: The markers each parser extracts (from the parser sources) -- checked
#: against the model's own chat template before a parser is assigned.
PARSER_MARKERS = {
    "gemma4": ["<|tool_call>"],
    "lfm2": ["<|tool_call_start|>"],
    "qwen3_coder": ["<function=", "<parameter="],
    "minicpm5": ["<function"],
    "hermes": ["<tool_call>"],
    "granite4": ["<tool_call>"],
    "mistral": ["[TOOL_CALLS]"],
}
#: Detection order when a family has no documented parser (most specific
#: marker first).
DETECT_ORDER = ("gemma4", "lfm2", "qwen3_coder", "hermes", "mistral")
ALL_MARKERS = sorted({m for ms in PARSER_MARKERS.values() for m in ms})

# Probe failure taxonomy (never collapsed into a generic PROBE_FAILED).
HOST_DRIVER_INCOMPATIBLE = "HOST_DRIVER_INCOMPATIBLE"
VLLM_RUNTIME_INCOMPATIBLE = "VLLM_RUNTIME_INCOMPATIBLE"
TRANSFORMERS_INCOMPATIBLE = "TRANSFORMERS_INCOMPATIBLE"
TOOL_PARSER_MISSING = "TOOL_PARSER_MISSING"
MODEL_SERVER_START_FAILED = "MODEL_SERVER_START_FAILED"
MODEL_DOWNLOAD_FAILED = "MODEL_DOWNLOAD_FAILED"
MODEL_TOOL_ROUNDTRIP_FAILED = "MODEL_TOOL_ROUNDTRIP_FAILED"
RESOURCE_BLOCKED = "RESOURCE_BLOCKED"
LICENSE_REVIEW_REQUIRED = "LICENSE_REVIEW_REQUIRED"
PIN_BLOCKED = "PIN_BLOCKED"
TAXONOMY = (HOST_DRIVER_INCOMPATIBLE, VLLM_RUNTIME_INCOMPATIBLE,
            TRANSFORMERS_INCOMPATIBLE, TOOL_PARSER_MISSING,
            MODEL_SERVER_START_FAILED, MODEL_DOWNLOAD_FAILED,
            MODEL_TOOL_ROUNDTRIP_FAILED, RESOURCE_BLOCKED,
            LICENSE_REVIEW_REQUIRED, PIN_BLOCKED)
HOST_BLOCK = "VLLM_HOST_DRIVER_INCOMPATIBLE"


# ---- host --------------------------------------------------------------------------

def _vt(v: str | None) -> tuple[int, ...] | None:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:3]) if nums else None


def parse_nvidia_smi(header: str, query_csv: str) -> dict[str, Any]:
    """`nvidia-smi` (header) + `nvidia-smi --query-gpu=name,driver_version,
    memory.total --format=csv,noheader`."""
    host_cuda = (re.search(r"CUDA Version:\s*([\d.]+)", header or "") or
                 [None, None])[1]
    rows = [r.strip() for r in (query_csv or "").splitlines() if r.strip()]
    gpu = driver = mem = None
    if rows:
        parts = [p.strip() for p in rows[0].split(",")]
        gpu = parts[0] if parts else None
        driver = parts[1] if len(parts) > 1 else None
        mem = parts[2] if len(parts) > 2 else None
    if driver is None:
        driver = (re.search(r"Driver Version:\s*([\d.]+)", header or "") or
                  [None, None])[1]
    return {"gpu": gpu, "gpu_count": len(rows), "driver_version": driver,
            "host_cuda": host_cuda, "gpu_memory": mem}


def read_host() -> dict[str, Any]:
    def run(*a: str) -> str:
        try:
            return subprocess.run(["nvidia-smi", *a], capture_output=True,
                                  text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    return parse_nvidia_smi(run(), run(
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader"))


def host_verdict(host: dict[str, Any], vllm_cuda: str = VLLM_CUDA
                 ) -> dict[str, Any]:
    need_s = DRIVER_MIN[vllm_cuda]
    need = _vt(need_s)
    have = _vt(host.get("driver_version"))
    hc = _vt(host.get("host_cuda"))
    reasons = []
    if have is None:
        reasons.append("NVIDIA driver version could not be read")
    elif have < need:
        reasons.append(f"driver {host['driver_version']} < {need_s} "
                       f"required by CUDA {vllm_cuda}")
    if hc is not None and hc < _vt(vllm_cuda):
        reasons.append(f"host CUDA {host['host_cuda']} < vLLM's CUDA "
                       f"{vllm_cuda} runtime")
    ok = not reasons
    return {"status": "COMPATIBLE" if ok else HOST_BLOCK,
            "driver_version": host.get("driver_version"),
            "host_cuda": host.get("host_cuda"), "gpu": host.get("gpu"),
            "vllm_version": VLLM_VERSION, "vllm_cuda": vllm_cuda,
            "minimum_required_driver": need_s,
            "driver_source": DRIVER_SOURCE, "reasons": reasons,
            "remediation": "" if ok else REMEDIATION}


def verdict_block(v: dict[str, Any]) -> str:
    lines = [] if v["status"] == "COMPATIBLE" else [HOST_BLOCK]
    lines += [f"gpu: {v.get('gpu')}",
              f"driver_version: {v['driver_version']}",
              f"host_cuda: {v['host_cuda']}",
              f"vllm_version: {v['vllm_version']}",
              f"vllm_cuda: {v['vllm_cuda']}",
              f"minimum_required_driver: {v['minimum_required_driver']}",
              f"cuda_compatibility: {v['status']}"]
    if v["status"] != "COMPATIBLE":
        lines += [f"reason: {'; '.join(v['reasons'])}", "remediation:",
                  "  redeploy the Pod on a RunPod host with a compatible "
                  "driver"]
    return "\n".join(lines)


# ---- wheel -------------------------------------------------------------------------

def fetch_wheel(dest: Path, opener=urllib.request.urlopen) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / WHEEL["filename"]
    if not out.exists() or _sha(out) != WHEEL["sha256"]:
        tmp = out.with_suffix(".part")
        with opener(WHEEL["url"], timeout=600) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        os.replace(tmp, out)
    got = _sha(out)
    if got != WHEEL["sha256"]:
        raise ValueError(f"wheel sha256 {got} != {WHEEL['sha256']}")
    return out


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- introspection inside the vLLM venv (no model, no GPU allocation) -------------

INTROSPECT = r'''
import importlib, importlib.metadata as md, json, platform, sys, traceback
req = json.loads(sys.argv[1])
out = {"python": platform.python_version(), "executable": sys.executable}
def ver(n):
    try:
        return md.version(n)
    except Exception:
        return None
out["versions"] = {n: ver(n) for n in req["packages"]}
try:
    d = md.distribution("vllm")
    out["vllm_wheel"] = {k: (d.read_text(f) or "").strip() for k, f in
                         (("WHEEL", "WHEEL"), ("INSTALLER", "INSTALLER"),
                          ("direct_url", "direct_url.json"))}
except Exception as e:
    out["vllm_wheel"] = {"error": f"{type(e).__name__}: {e}"}
try:
    import torch
    out["torch_cuda"] = torch.version.cuda
    try:
        torch.cuda.init()
        out["cuda_init"] = {"ok": True, "devices": torch.cuda.device_count(),
                            "device": torch.cuda.get_device_name(0)}
    except Exception as e:
        out["cuda_init"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
except Exception as e:
    out["torch_cuda"] = None
    out["cuda_init"] = {"ok": False, "error": f"torch import {type(e).__name__}: {e}"}
def registry(mod, attr, getter, wanted):
    try:
        mgr = getattr(importlib.import_module(mod), attr)
        names = set(mgr.list_registered())
        names |= set(getattr(mgr, "lazy_parsers", {}) or {})
        loaded = {}
        for n in wanted:
            try:
                getattr(mgr, getter)(n)
                loaded[n] = "ok"
            except Exception as e:
                loaded[n] = f"{type(e).__name__}: {e}"
        return {"ok": True, "names": sorted(names), "loaded": loaded}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "trace_tail": traceback.format_exc()[-1200:]}
out["tool_parsers"] = registry("vllm.tool_parsers", "ToolParserManager",
                               "get_tool_parser", req["tool_parsers"])
out["reasoning_parsers"] = registry("vllm.reasoning", "ReasoningParserManager",
                                    "get_reasoning_parser",
                                    req["reasoning_parsers"])
out["archs"] = {}
try:
    R = importlib.import_module("vllm.model_executor.models.registry")
    table = {}
    for k in dir(R):
        v = getattr(R, k)
        if k.startswith("_") and k.endswith("_MODELS") and isinstance(v, dict):
            table.update(v)
except Exception as e:
    table = None
    out["registry_error"] = f"{type(e).__name__}: {e}"
for a in req["archs"]:
    if table is None or a not in table:
        out["archs"][a] = {"ok": False, "error":
                           "architecture not in this vLLM's model registry"}
        continue
    mod, cls = table[a][0], table[a][1]
    try:
        m = importlib.import_module(f"vllm.model_executor.models.{mod}")
        getattr(m, cls)
        out["archs"][a] = {"ok": True, "module": mod}
    except BaseException as e:
        out["archs"][a] = {"ok": False, "module": mod,
                           "error": f"{type(e).__name__}: {e}",
                           "trace_tail": traceback.format_exc()[-1500:]}
print("@@VLLM_RUNTIME@@" + json.dumps(out))
'''


def introspect(python: str, *, archs: list[str], tool_parsers: list[str],
               reasoning_parsers: list[str], timeout: int = 900
               ) -> dict[str, Any]:
    req = {"packages": sorted(LOCK), "archs": sorted(set(archs)),
           "tool_parsers": sorted(set(tool_parsers)),
           "reasoning_parsers": sorted(set(reasoning_parsers))}
    env = dict(os.environ)
    env.setdefault("VLLM_NO_USAGE_STATS", "1")
    env.setdefault("DO_NOT_TRACK", "1")
    p = subprocess.run([python, "-c", INTROSPECT, json.dumps(req)],
                       capture_output=True, text=True, timeout=timeout,
                       env=env)
    for line in p.stdout.splitlines():
        if line.startswith("@@VLLM_RUNTIME@@"):
            return json.loads(line[len("@@VLLM_RUNTIME@@"):])
    return {"error": f"introspection failed rc={p.returncode}",
            "stderr_tail": (p.stderr or "")[-2000:]}


def classify_error(text: str) -> str:
    t = text or ""
    if re.search(r"NVIDIA driver on your system is too old|"
                 r"CUDA driver version is insufficient|"
                 r"cudaErrorInsufficientDriver", t, re.I):
        return HOST_DRIVER_INCOMPATIBLE
    if re.search(r"(cannot import name|ImportError|ModuleNotFoundError)"
                 r"[^\n]*transformers|transformers[/.][^\n]*"
                 r"(ImportError|cannot import)", t):
        return TRANSFORMERS_INCOMPATIBLE
    return VLLM_RUNTIME_INCOMPATIBLE


def lock_mismatches(intro: dict[str, Any]) -> list[str]:
    v = intro.get("versions") or {}
    out = [f"{k}=={v.get(k)} (expected {want})" for k, want in LOCK.items()
           if (v.get(k) or "").split("+")[0] != want]
    if (intro.get("python") or "").rsplit(".", 1)[0] != PYTHON:
        out.append(f"python {intro.get('python')} (expected {PYTHON}.x)")
    tc = intro.get("torch_cuda")
    if tc and _vt(tc)[:2] != _vt(VLLM_CUDA)[:2]:
        out.append(f"torch CUDA {tc} (expected {VLLM_CUDA})")
    return out


# ---- per-model parser plan (pure) ---------------------------------------------------

def parser_plan(runpod: dict[str, Any], markers: list[str] | None,
                registered_tool: list[str] | tuple[str, ...],
                registered_reasoning: list[str] | tuple[str, ...]
                ) -> dict[str, Any]:
    """Pick the tool parser from the family's documented candidates,
    confirmed against the markers found in the model's own chat template,
    and verify it (and the reasoning parser) is registered. Families with
    no documented parser are detected from the template markers only."""
    cands = list(runpod.get("tool_parser_candidates") or [])
    template_from_tokenizer = bool(runpod.get("template_from_mistral_common"))
    found = set(markers or [])
    evidence, chosen = "", None

    def matches(p: str) -> bool:
        return all(m in found for m in PARSER_MARKERS.get(p, []))
    if cands:
        if markers is None or template_from_tokenizer:
            chosen = cands[0]
            evidence = ("chat template supplied by the tokenizer backend "
                        "(mistral-common)" if template_from_tokenizer else
                        "chat template not inspected yet; documented "
                        "family parser")
        else:
            chosen = next((p for p in cands if matches(p)), None)
            evidence = (f"template markers {sorted(found)} match {chosen}"
                        if chosen else "")
            if chosen is None:
                chosen = cands[0]
                evidence = (f"WARNING: template markers {sorted(found)} do "
                            f"not show {PARSER_MARKERS.get(chosen)}; the "
                            f"probe decides")
    elif markers:
        chosen = next((p for p in DETECT_ORDER if matches(p)), None)
        evidence = (f"detected from template markers {sorted(found)}"
                    if chosen else "")
    rp = runpod.get("reasoning_parser")
    out = {"tool_call_parser": chosen, "reasoning_parser": rp,
           "evidence": evidence, "status": "ASSIGNED_UNPROVEN",
           "failure_class": None, "detail": ""}
    if chosen is None:
        out |= {"status": TOOL_PARSER_MISSING,
                "failure_class": TOOL_PARSER_MISSING,
                "detail": "no documented tool parser for this family and no "
                          "known tool-call marker in its chat template"}
    elif chosen not in registered_tool:
        out |= {"status": TOOL_PARSER_MISSING,
                "failure_class": TOOL_PARSER_MISSING,
                "detail": f"tool parser {chosen!r} is not registered by "
                          f"this vLLM"}
    elif rp and rp not in registered_reasoning:
        out |= {"status": TOOL_PARSER_MISSING,
                "failure_class": TOOL_PARSER_MISSING,
                "detail": f"reasoning parser {rp!r} is not registered by "
                          f"this vLLM"}
    return out


# ---- manifest ---------------------------------------------------------------------

def manifest_path(runtime: Path) -> Path:
    return runtime / "vllm_runtime" / "RUNTIME_MANIFEST.json"


def load_manifest(runtime: Path) -> dict[str, Any] | None:
    p = manifest_path(runtime)
    return json.loads(p.read_text()) if p.exists() else None


def save_manifest(runtime: Path, man: dict[str, Any]) -> Path:
    p = manifest_path(runtime)
    p.parent.mkdir(parents=True, exist_ok=True)
    man["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(man, indent=1, sort_keys=True, default=str))
    os.replace(tmp, p)            # byte write + rename: no chmod (geesefs)
    return p


def requested() -> dict[str, Any]:
    return {"vllm": VLLM_VERSION, "wheel": WHEEL, "python": PYTHON,
            "lock": LOCK, "lock_source": LOCK_SOURCE,
            "constraints_file": CONSTRAINTS.name,
            "constraints_sha256": _sha(CONSTRAINTS)}


def profile_preflight(raw: dict[str, Any], intro: dict[str, Any] | None
                      ) -> dict[str, Any]:
    """Runtime readiness of one profile against the installed vLLM."""
    rp = raw.get("runpod") or {}
    art = raw.get("artifact") or {}
    archs = list(rp.get("preflight_architectures") or
                 art.get("architecture") or [])
    tool = rp.get("tool_call_parser") or rp.get("suggested_tool_call_parser")
    reason = rp.get("reasoning_parser") or rp.get(
        "suggested_reasoning_parser")
    res: dict[str, Any] = {"tool_call_parser": tool,
                           "reasoning_parser": reason,
                           "architectures": archs, "imports": {}}
    if intro is None or intro.get("error"):
        return res | {"status": VLLM_RUNTIME_INCOMPATIBLE,
                      "detail": "vLLM environment not introspected"}
    tp, rpar = intro.get("tool_parsers") or {}, intro.get(
        "reasoning_parsers") or {}
    if not tp.get("ok"):
        return res | {"status": VLLM_RUNTIME_INCOMPATIBLE,
                      "detail": f"tool parser registry: {tp.get('error')}"}
    if not tool:
        return res | {"status": TOOL_PARSER_MISSING,
                      "detail": "no tool-call parser assigned"}
    if tool not in (tp.get("names") or []) or \
            (tp.get("loaded") or {}).get(tool, "ok") != "ok":
        return res | {"status": TOOL_PARSER_MISSING,
                      "detail": f"tool parser {tool!r} not registered/"
                                f"loadable: {(tp.get('loaded') or {}).get(tool)}"}
    if reason and (reason not in (rpar.get("names") or []) or
                   (rpar.get("loaded") or {}).get(reason, "ok") != "ok"):
        return res | {"status": TOOL_PARSER_MISSING,
                      "detail": f"reasoning parser {reason!r} not "
                                f"registered/loadable"}
    for a in archs:
        r = (intro.get("archs") or {}).get(a)
        res["imports"][a] = r
        if r is None:
            return res | {"status": VLLM_RUNTIME_INCOMPATIBLE,
                          "detail": f"architecture {a} was not checked"}
        if not r.get("ok"):
            cls = classify_error(f"{r.get('error')}\n{r.get('trace_tail')}")
            return res | {"status": cls,
                          "detail": f"{a}: {r.get('error')}"}
    if not archs:
        return res | {"status": VLLM_RUNTIME_INCOMPATIBLE,
                      "detail": "architecture unknown (pin the model first)"}
    return res | {"status": "RUNTIME_READY", "detail": ""}


def build_manifest(host: dict[str, Any], intro: dict[str, Any] | None,
                   profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    v = host_verdict(host)
    man: dict[str, Any] = {"host": host, "verdict": v,
                           "requested": requested(), "installed": None,
                           "lock_mismatches": [], "profiles": {}}
    if v["status"] != "COMPATIBLE":
        man["profiles"] = {pid: {"status": HOST_DRIVER_INCOMPATIBLE,
                                 "detail": "; ".join(v["reasons"])}
                           for pid in profiles}
        return man
    if intro is not None:
        man["installed"] = {k: intro.get(k) for k in (
            "python", "versions", "torch_cuda", "vllm_wheel", "cuda_init",
            "error", "stderr_tail")}
        man["parsers"] = {
            "tool": (intro.get("tool_parsers") or {}).get("names"),
            "reasoning": (intro.get("reasoning_parsers") or {}).get("names")}
        man["lock_mismatches"] = lock_mismatches(intro) \
            if not intro.get("error") else ["introspection failed"]
        ci = intro.get("cuda_init") or {}
        if not ci.get("ok"):
            cls = classify_error(ci.get("error") or "")
            if cls == HOST_DRIVER_INCOMPATIBLE:
                v = man["verdict"] = v | {
                    "status": HOST_BLOCK, "empirical": ci.get("error"),
                    "reasons": v["reasons"] + [f"torch CUDA init: "
                                               f"{ci.get('error')}"],
                    "remediation": REMEDIATION}
                man["profiles"] = {pid: {"status": HOST_DRIVER_INCOMPATIBLE,
                                         "detail": ci.get("error")}
                                   for pid in profiles}
                return man
    for pid, raw in profiles.items():
        r = profile_preflight(raw, intro)
        if man["lock_mismatches"] and r["status"] == "RUNTIME_READY":
            r |= {"status": VLLM_RUNTIME_INCOMPATIBLE,
                  "detail": "installed environment differs from the lock: "
                            + "; ".join(man["lock_mismatches"])}
        man["profiles"][pid] = r
    return man


def profile_gate(man: dict[str, Any] | None, pid: str
                 ) -> dict[str, Any] | None:
    """Why a profile must NOT be served, from the persisted manifest."""
    if man is None:
        return {"probe_status": VLLM_RUNTIME_INCOMPATIBLE,
                "failure": "the vLLM runtime preflight has not run on this "
                           "host (vllm_runtime.py preflight)"}
    if man["verdict"]["status"] != "COMPATIBLE":
        return {"probe_status": HOST_DRIVER_INCOMPATIBLE,
                "failure": "; ".join(man["verdict"]["reasons"]) + " -- "
                           + man["verdict"]["remediation"]}
    r = (man.get("profiles") or {}).get(pid)
    if r is None:
        return {"probe_status": VLLM_RUNTIME_INCOMPATIBLE,
                "failure": f"{pid} was not covered by the runtime preflight"}
    if r["status"] != "RUNTIME_READY":
        return {"probe_status": r["status"], "failure": r.get("detail", "")}
    return None


# ---- server logs and downloads ----------------------------------------------------

#: Harmless on the Global Volume (fuse.geesefs refuses chmod): huggingface_hub
#: logs these and continues with the downloaded file.
CHMOD_NOISE = re.compile(r"(Could not set the permissions on the file|"
                         r"Continuing without setting permissions|"
                         r"chmod[^\n]*Operation not permitted|"
                         r"Operation not permitted[^\n]*chmod|"
                         r"\[Errno 1\] Operation not permitted)", re.I)


def classify_server_log(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines()
             if not CHMOD_NOISE.search(ln)]
    t = "\n".join(lines)
    cls = classify_error(t)
    if cls != VLLM_RUNTIME_INCOMPATIBLE:
        return cls
    if re.search(r"invalid tool parser|tool[_-]call[_-]parser[^\n]*"
                 r"(invalid|not (found|registered|supported))|"
                 r"KeyError: [^\n]*parser", t, re.I):
        return TOOL_PARSER_MISSING
    if re.search(r"CUDA out of memory|OutOfMemoryError|"
                 r"not enough (GPU )?memory|No available memory for the "
                 r"cache blocks|exceeds (the )?available", t, re.I):
        return RESOURCE_BLOCKED
    if re.search(r"RepositoryNotFoundError|RevisionNotFoundError|"
                 r"GatedRepoError|LocalEntryNotFoundError|EntryNotFoundError|"
                 r"HfHubHTTPError|401 Client Error|403 Client Error|"
                 r"404 Client Error|No space left on device|"
                 r"ReadTimeout|ConnectionError|Connection reset|"
                 r"Consistency check failed|IncompleteRead", t, re.I):
        return MODEL_DOWNLOAD_FAILED
    return MODEL_SERVER_START_FAILED


def verify_download(pin: dict[str, Any], cache_dir: Path) -> dict[str, Any]:
    """Every pinned weight file present in the persistent HF cache at the
    pinned revision with the pinned size. Permission bits are irrelevant
    (and cannot be changed on the Global Volume)."""
    repo, rev = pin.get("repository"), pin.get("revision")
    if not repo or not rev:
        return {"ok": False, "detail": "no pin"}
    snap = cache_dir / f"models--{repo.replace('/', '--')}" / "snapshots" / rev
    missing, wrong = [], []
    for w in pin.get("weights") or []:
        f = snap / w["file"]
        if not f.exists():
            missing.append(w["file"])
        elif w.get("bytes") and f.stat().st_size != w["bytes"]:
            wrong.append(w["file"])
    return {"ok": bool(pin.get("weights")) and not missing and not wrong,
            "snapshot": str(snap), "missing": missing, "size_mismatch": wrong}


# ---- CLI --------------------------------------------------------------------------

def _suite_profiles(profiles_dir: Path) -> dict[str, dict[str, Any]]:
    suite = json.loads((profiles_dir / "_runpod_suite.json").read_text())
    return {m["profile_id"]: json.loads(
        (profiles_dir / f"{m['profile_id']}.json").read_text())
        for m in suite["models"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("command", choices=("host", "fetch-wheel", "preflight",
                                        "show"))
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(ROOT / "artifacts" /
                                     "model_comparison" / "runtime")))
    ap.add_argument("--venv-python")
    ap.add_argument("--dest")
    ap.add_argument("--profiles-dir", default=str(ROOT / "profiles"))
    args = ap.parse_args(argv)
    runtime = Path(args.runtime_dir)
    if args.command == "fetch-wheel":
        try:
            print(fetch_wheel(Path(args.dest)))
            return 0
        except Exception as exc:  # noqa: BLE001
            print(f"VLLM_WHEEL_UNVERIFIED: {exc}", file=sys.stderr)
            return 8
    if args.command == "show":                   # read-only
        man = load_manifest(runtime)
        if man is None:
            print("no vLLM runtime manifest yet")
            return 1
        print(verdict_block(man["verdict"]))
        return 0 if man["verdict"]["status"] == "COMPATIBLE" else 7
    host = read_host()
    profiles = _suite_profiles(Path(args.profiles_dir))
    if args.command == "host":
        man = build_manifest(host, None, profiles)
        man["stage"] = "host gate (before vLLM install)"
        save_manifest(runtime, man)
        print(verdict_block(man["verdict"]))
        return 0 if man["verdict"]["status"] == "COMPATIBLE" else 7
    if not args.venv_python:
        ap.error("preflight needs --venv-python")
    v = host_verdict(host)
    intro = None
    if v["status"] == "COMPATIBLE":
        archs, tools, reasons = [], [], []
        for raw in profiles.values():
            rp, art = raw.get("runpod") or {}, raw.get("artifact") or {}
            archs += list(rp.get("preflight_architectures") or
                          art.get("architecture") or [])
            for k, bucket in (("tool_call_parser", tools),
                              ("suggested_tool_call_parser", tools),
                              ("reasoning_parser", reasons),
                              ("suggested_reasoning_parser", reasons)):
                if rp.get(k):
                    bucket.append(rp[k])
        intro = introspect(args.venv_python, archs=[a for a in archs if a],
                           tool_parsers=tools, reasoning_parsers=reasons)
    man = build_manifest(host, intro, profiles)
    man["stage"] = "runtime preflight (installed vLLM, no model)"
    p = save_manifest(runtime, man)
    print(verdict_block(man["verdict"]))
    if man["verdict"]["status"] != "COMPATIBLE":
        return 7
    inst = man.get("installed") or {}
    print(f"installed: python {inst.get('python')}, "
          + ", ".join(f"{k} {(inst.get('versions') or {}).get(k)}"
                      for k in ("vllm", "torch", "transformers", "tokenizers"))
          + f", torch CUDA {inst.get('torch_cuda')}")
    if man["lock_mismatches"]:
        print(f"{VLLM_RUNTIME_INCOMPATIBLE}: " + "; ".join(
            man["lock_mismatches"]))
    for pid, r in man["profiles"].items():
        print(f"  {pid:32} {r['status']:26} tool={r.get('tool_call_parser')}"
              f" reasoning={r.get('reasoning_parser')} {r.get('detail', '')[:90]}")
    print(f"runtime manifest: {p}")
    return 9 if man["lock_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
