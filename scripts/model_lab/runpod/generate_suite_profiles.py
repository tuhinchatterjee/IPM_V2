"""
Generate the RunPod A40 (vLLM, OpenAI-compatible) candidate profiles.

    python scripts/model_lab/runpod/generate_suite_profiles.py

Each served checkpoint is a DIFFERENT artifact from the Mac's Ollama tags, so
it gets its own profile (`<id>-runpod`). Nothing is substituted:

* a known repository id is registered NOT_INSTALLED with
  `artifact.revision_required = true`; it cannot run until the exact revision
  is pinned (scripts/model_lab/verify_checkpoints.py) and the probe passes;
* a model whose exact repository is not verified here (no Hugging Face access
  from the build environment) is registered DISCOVERED -- never runnable --
  with the search term to verify on the pod;
* a checkpoint that cannot fit the A40 at the stated precision is
  BLOCKED_RESOURCE with the arithmetic.

Tool-call parsers are SUGGESTIONS until `probe.py` proves forced tool use,
round trip and stop-reason mapping on the served endpoint.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "profiles"

A40_GB = 48

#: (profile stem, display, family, repo id or None, params, bf16 GB,
#:  suggested vLLM tool parser, extra vLLM args, status override, note)
MODELS = [
    ("minicpm5-2b", "MiniCPM5-2B", "MiniCPM", None, "2B", 5, None, [],
     None, "exact repository not verified in the build environment"),
    ("lfm2.5-vl-3b", "LFM2.5-VL-3B", "LFM", None, "3B", 7, None, [],
     None, "vision-language model used text-only; exact repository not "
           "verified in the build environment"),
    ("qwen3.5-4b", "Qwen3.5-4B", "Qwen", "Qwen/Qwen3.5-4B", "4B", 9,
     "hermes", ["--reasoning-parser", "qwen3"], None, ""),
    ("fin-r1-7b", "Fin-R1 7B", "Fin-R1", "SUFE-AIFLM-Lab/Fin-R1", "7B", 16,
     "hermes", [], None, "diagnostic-only until mandatory controls pass"),
    ("granite-4.2-8b", "Granite 4.2 8B", "Granite",
     "ibm-granite/granite-4.2-8b", "8B", 17, "granite", [], None, ""),
    ("ministral-3-8b", "Ministral 3 8B", "Mistral",
     "mistralai/Ministral-3-8B-Instruct-2512", "8B", 17, "mistral",
     ["--tokenizer-mode", "mistral"], None, ""),
    ("qwen3.5-9b", "Qwen3.5-9B", "Qwen", "Qwen/Qwen3.5-9B", "9B", 19,
     "hermes", ["--reasoning-parser", "qwen3"], None, ""),
    ("ornith-1.5-9b", "Ornith-1.5-9B", "Ornith", None, "9B", 19, None, [],
     None, "exact repository not verified in the build environment"),
    ("gemma-4-12b", "Gemma 4 12B", "Gemma", "google/gemma-4-12B-it", "12B",
     25, None, [], None, "tool-call parser for this family unqualified"),
    ("gpt-oss-20b", "gpt-oss-20b", "gpt-oss", "openai/gpt-oss-20b",
     "21B (MoE)", 14, "openai", [], None,
     "publisher MXFP4 weights (~14 GB)"),
    ("qwen3.8-27b", "Qwen3.8-27B", "Qwen", "Qwen/Qwen3.8-27B", "27B", 55,
     "hermes", ["--reasoning-parser", "qwen3"], "BLOCKED_RESOURCE",
     "bf16 weights ~55 GB exceed the A40's 48 GB; a quantised checkpoint "
     "would be a different artifact and must be registered separately"),
]


def profile(stem, display, family, repo, params, gb, parser, extra,
            status, note) -> dict:
    pid = f"{stem}-runpod"
    verified = repo is not None
    if status is None:
        status = "NOT_INSTALLED" if verified else "DISCOVERED"
    return {
        "profile_id": pid,
        "display_name": f"{display} (RunPod A40, vLLM)",
        "role": "candidate", "family": family,
        "registry_id": repo or f"UNVERIFIED:{display}",
        "identity_source": ("lab registry (master prompt v2.1); exact "
                            "revision to pin on the pod" if verified else
                            "NOT VERIFIED: search term only"),
        "route": "openai_compat", "status": status,
        "status_reason": note or ("Served by vLLM on the RunPod A40; needs "
                                  "a pinned revision and a passing probe."),
        "recovery": (f"On the pod: scripts/model_lab/verify_checkpoints.py "
                     f"--profile {pid}; record artifact.revision; "
                     f"scripts/model_lab/runpod/serve.sh {pid}; "
                     f"scripts/model_lab/probe.py --profile {pid}"),
        "parameters_total": params,
        "endpoint": {"class": "local_loopback",
                     "base_url_env": "LAB_VLLM_OPENAI_URL",
                     "base_url_default": "http://127.0.0.1:8000/v1",
                     "model": repo or f"UNVERIFIED:{display}",
                     "api_key_env": None},
        "context_tokens": 32768,
        "max_output_tokens": 8192,
        "limitations": ["Different artifact from any Ollama/Mac profile; "
                        "never substituted for it."] + ([note] if note
                                                       else []),
        "allowed_modes": ["E2E_BASELINE", "OBSERVED_STAGE_EVIDENCE"],
        "deployment_profiles": ["runpod_a40_sequential"],
        "requires_probe": True,
        "supported_controls": {"tools": None, "forced_tool_use": None,
                               "named_tool_forcing": None,
                               "tool_result_roundtrip": None,
                               "stop_reason_mapping": None,
                               "effort_control": False,
                               "token_counting": False},
        "price": {"input_usd_per_mtok": 0.0, "output_usd_per_mtok": 0.0,
                  "cache_write_usd_per_mtok": 0.0,
                  "cache_read_usd_per_mtok": 0.0,
                  "basis": "no token charge; RunPod GPU time is billed by "
                           "the hour and reported separately",
                  "verified_at": "2026-09-30",
                  "source": "lab local-inference policy"},
        "licence": "UNVERIFIED - read the model card before activation",
        "provenance_status": "UNVERIFIED",
        "artifact": {"kind": "hf_repository", "repository": repo,
                     "revision": None, "revision_required": True,
                     "search_term": None if verified else display,
                     "weights_gb_bf16_estimate": gb,
                     "fits_a40_48gb": gb <= A40_GB - 6},
        "runpod": {"server": "vllm", "served_model_name": repo,
                   "max_model_len": 32768,
                   "suggested_tool_call_parser": parser,
                   "parser_status": "UNQUALIFIED until probe.py passes",
                   "extra_args": extra,
                   "host": "127.0.0.1", "port": 8000},
        "observed_probes": [],
    }


def main() -> int:
    for m in MODELS:
        p = profile(*m)
        path = OUT / f"{p['profile_id']}.json"
        path.write_text(json.dumps(p, indent=1, ensure_ascii=False) + "\n")
        print(f"{p['status']:17} {p['profile_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
