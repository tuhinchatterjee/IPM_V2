"""
Generate the RunPod A40 (vLLM, OpenAI-compatible) candidate profiles.

    python scripts/model_lab/runpod/generate_suite_profiles.py

Each served checkpoint is a DIFFERENT artifact from the Mac's Ollama tags, so
it gets its own profile (`<id>-runpod`). Nothing is substituted, nothing is
pinned here: `pin_and_probe_models.py` resolves and pins on the pod.

* `source` says where the official artifact must come from: an exact
  repository when it is known, otherwise the publisher organisation and a
  name pattern. Resolution accepts exactly ONE match; anything else is
  PIN_BLOCKED.
* A checkpoint that cannot fit the A40 at native precision stays in the
  registry marked RESOURCE_BLOCKED_A40. A quantised deployment is a
  SEPARATE profile (`<base>--awq-4bit`) with `parent_profile_id`,
  `quantization` and its own artifact; it never overwrites the base.
* Tool-call and reasoning parsers are SUGGESTIONS until the probe proves
  forced tool use, the round trip and stop-reason mapping.

Re-running keeps any pin already recorded in an existing profile file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "profiles"

#: Run order: smallest / cheapest first.
#: (stem, display, family, source, params, bf16 GB estimate, tool parser,
#:  reasoning parser, extra vLLM args, note)
MODELS = [
    ("minicpm5-2b", "MiniCPM5-2B", "MiniCPM",
     {"org": "openbmb", "name_pattern": r"^MiniCPM5[-_.]?2B$"}, "2B", 5,
     None, None, [], "exact repository resolved on the pod"),
    ("lfm2.5-vl-3b", "LFM2.5-VL-3B", "LFM",
     {"org": "LiquidAI", "name_pattern": r"^LFM2\.5-VL-3B$"}, "3B", 7,
     None, None, [], "vision-language model, used text-only"),
    ("qwen3.5-4b", "Qwen3.5-4B", "Qwen", {"repository": "Qwen/Qwen3.5-4B"},
     "4B", 9, "hermes", "qwen3", [], ""),
    ("fin-r1-7b", "Fin-R1 7B", "Fin-R1",
     {"repository": "SUFE-AIFLM-Lab/Fin-R1"}, "7B", 16, "hermes", None, [],
     "diagnostic-only until the mandatory controls pass"),
    ("granite-4.2-8b", "Granite 4.2 8B", "Granite",
     {"repository": "ibm-granite/granite-4.2-8b"}, "8B", 17, "granite",
     None, [], ""),
    ("ministral-3-8b", "Ministral 3 8B", "Mistral",
     {"repository": "mistralai/Ministral-3-8B-Instruct-2512"}, "8B", 17,
     "mistral", None, ["--tokenizer-mode", "mistral"], ""),
    ("qwen3.5-9b", "Qwen3.5-9B", "Qwen", {"repository": "Qwen/Qwen3.5-9B"},
     "9B", 19, "hermes", "qwen3", [], ""),
    ("ornith-1.5-9b", "Ornith-1.5-9B", "Ornith",
     {"org": None, "name_pattern": r"^Ornith-1\.5-9B$"}, "9B", 19, None,
     None, [], "publisher organisation unknown: PIN_BLOCKED until the "
                "operator names the official repository"),
    ("gemma-4-12b", "Gemma 4 12B", "Gemma",
     {"repository": "google/gemma-4-12B-it"}, "12B", 25, None, None, [],
     "tool-call parser for this family unqualified"),
    ("gpt-oss-20b", "gpt-oss-20b", "gpt-oss",
     {"repository": "openai/gpt-oss-20b"}, "21B (MoE)", 14, "openai", None,
     [], "publisher MXFP4 weights"),
    ("qwen3.8-27b", "Qwen3.8-27B", "Qwen",
     {"repository": "Qwen/Qwen3.8-27B"}, "27B", 55, "hermes", "qwen3", [],
     "RESOURCE_BLOCKED_A40: bf16 weights ~55 GB exceed 48 GB"),
]

#: Explicit quantised deployment variants (never substitutes).
VARIANTS = [
    ("qwen3.8-27b", "awq-4bit",
     {"org": "Qwen", "name_pattern": r"^Qwen3\.8-27B-AWQ$"},
     ["--quantization", "awq"], 15,
     "the bf16 checkpoint does not fit the A40; a 4-bit AWQ artifact from "
     "the publisher is a separate deployment variant of the same base "
     "model, and is used only if its identity is verified on the pod"),
]


def _base(stem, display, family, source, params, gb, parser, rparser,
          extra, note) -> dict:
    pid = f"{stem}-runpod"
    blocked = "RESOURCE_BLOCKED_A40" in note
    known = "repository" in source
    extra_args = list(extra) + (["--reasoning-parser", rparser]
                                if rparser else [])
    return {
        "profile_id": pid, "display_name": f"{display} (RunPod A40, vLLM)",
        "role": "candidate", "family": family,
        "registry_id": source.get("repository") or f"UNPINNED:{display}",
        "identity_source": "resolved and pinned on the pod by "
                           "pin_and_probe_models.py",
        "route": "openai_compat",
        "status": ("BLOCKED_RESOURCE" if blocked else
                   "NOT_INSTALLED" if known else "DISCOVERED"),
        "status_reason": note or "Needs a pinned revision, a fit check and "
                                 "a passing probe on the pod.",
        "recovery": f"On the pod: scripts/model_lab/runpod/"
                    f"pin_and_probe_models.py --profile {pid} --probe",
        "parameters_total": params,
        "endpoint": {"class": "local_loopback",
                     "base_url_env": "LAB_VLLM_OPENAI_URL",
                     "base_url_default": "http://127.0.0.1:8000/v1",
                     "model": source.get("repository") or
                     f"UNPINNED:{display}", "api_key_env": None},
        "context_tokens": 32768, "max_output_tokens": 8192,
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
        "licence": "UNDETERMINED until pinned",
        "provenance_status": "UNVERIFIED",
        "artifact": {"kind": "hf_repository", "source": source,
                     "repository": source.get("repository"),
                     "revision": None, "revision_required": True,
                     "pin_status": "UNPINNED",
                     "license_status": "UNDETERMINED",
                     "quantization": None,
                     "weights_gb_bf16_estimate": gb},
        "runpod": {"server": "vllm",
                   "served_model_name": source.get("repository"),
                   "max_model_len": 32768,
                   "suggested_tool_call_parser": parser,
                   "suggested_reasoning_parser": rparser,
                   "parser_status": "UNQUALIFIED until the probe passes",
                   "extra_args": extra_args,
                   "host": "127.0.0.1", "port": 8000,
                   "fit": None, "resource_status": (
                       "RESOURCE_BLOCKED_A40" if blocked else
                       "FIT_NOT_COMPUTED")},
        "observed_probes": [],
    }


def _variant(base: dict, quant, source, args, gb, reason) -> dict:
    v = json.loads(json.dumps(base))
    v["profile_id"] = f"{base['profile_id']}--{quant}"
    v["display_name"] = base["display_name"].replace(
        "(RunPod", f"— {quant.upper()} (RunPod")
    v["parent_profile_id"] = base["profile_id"]
    v["variant_kind"] = "quantized_deployment"
    v["variant_note"] = reason
    v["status"] = "DISCOVERED"
    v["status_reason"] = ("quantised artifact not yet verified: resolved on "
                          "the pod from the publisher only")
    v["registry_id"] = f"UNPINNED:{v['display_name']}"
    v["endpoint"]["model"] = v["registry_id"]
    v["artifact"].update({"source": source, "repository": None,
                          "quantization": quant,
                          "weights_gb_bf16_estimate": None,
                          "weights_gb_estimate": gb})
    v["runpod"].update({"served_model_name": None,
                        "extra_args": list(args) + (
                            base["runpod"]["extra_args"]),
                        "resource_status": "FIT_NOT_COMPUTED"})
    v["limitations"] = base["limitations"][:1] + [
        f"Quantised deployment variant ({quant}) of {base['profile_id']}: "
        f"results are for this variant, not the bf16 base."]
    v["recovery"] = (f"On the pod: scripts/model_lab/runpod/"
                     f"pin_and_probe_models.py --profile {v['profile_id']} "
                     f"--probe")
    return v


def _keep_pin(new: dict, path: Path) -> dict:
    """Never throw away a pin recorded on the pod."""
    if not path.exists():
        return new
    old = json.loads(path.read_text())
    if (old.get("artifact") or {}).get("revision"):
        for k in ("registry_id", "endpoint", "artifact", "runpod", "status",
                  "status_reason", "licence", "provenance_status",
                  "identity_source", "context_tokens"):
            new[k] = old[k]
    return new


def main() -> int:
    bases = {}
    for m in MODELS:
        p = _base(*m)
        bases[m[0]] = p
        path = OUT / f"{p['profile_id']}.json"
        p = _keep_pin(p, path)
        path.write_text(json.dumps(p, indent=1, ensure_ascii=False) + "\n")
        print(f"{p['status']:17} {p['profile_id']}")
    for stem, quant, source, args, gb, reason in VARIANTS:
        v = _variant(bases[stem], quant, source, args, gb, reason)
        path = OUT / f"{v['profile_id']}.json"
        v = _keep_pin(v, path)
        path.write_text(json.dumps(v, indent=1, ensure_ascii=False) + "\n")
        print(f"{v['status']:17} {v['profile_id']}  (variant)")
    return 0




def write_suite() -> Path:
    """The versioned suite config, derived from the question registry."""
    sys.path.insert(0, str(ROOT))
    from backend.model_lab import benchmark_questions as bq

    models = []
    for m in MODELS:
        models.append({"model": m[1], "profile_id": f"{m[0]}-runpod",
                       "parameters": m[4]})
        for stem, quant, *_ in VARIANTS:
            if stem == m[0]:
                models.append({"model": f"{m[1]} {quant.upper()}",
                               "profile_id": f"{m[0]}-runpod--{quant}",
                               "parent_profile_id": f"{m[0]}-runpod",
                               "parameters": m[4], "quantization": quant})
    suite = {
        "suite_id": bq.SUITE_VERSION, "suite_schema": 2,
        "status": "PREPARED — no benchmark call has been made",
        "hardware": {"provider": "RunPod", "gpu": "NVIDIA A40",
                     "vram_gb": 48, "storage": "/workspace"},
        "deployment": "runpod_a40_sequential",
        "server": "vLLM OpenAI-compatible, 127.0.0.1:8000, one resident "
                  "model at a time",
        "frozen_source": "245c50e45786c6e0c866b281f9dd74da17d160b5",
        "trace": {"required": True, "flag": "MODEL_LAB_FULL_IO_TRACE=true"},
        "oracle_version": "lab-oracle-suite-1",
        "reference": {"saved_opus_comparison": "cmp-f364d8b6901a",
                      "applies_to": ["Q01"]},
        "run_order": "smallest / cheapest first (list order)",
        "per_model_sequence": [
            "qualification: pinned, licence clear, fits the A40, probe "
            "READY_E2E",
            "FROZEN_BASELINE Q01 (frozen limits)",
            "FROZEN_BASELINE Q02..Q15",
            "ASSISTED_V1 Q01..Q15"],
        "checkpoint": "after every question; a re-run resumes",
        "lanes": {
            "FROZEN_BASELINE": {"status": "READY", "definition":
                                "the unchanged frozen AdvancedCockpit "
                                "engine, prompts, tools and limits"},
            "ASSISTED_V1": {"status": "READY", "packet_version":
                            "assisted-v1.0", "definition":
                            "FROZEN_BASELINE plus the deterministic "
                            "per-question assistance packet appended as "
                            "one system block (backend/model_lab/"
                            "assistance.py)"}},
        "models": models,
        "excluded_from_analyst_benchmark": [
            {"model": "Julia-1", "reason": "not an analyst-answer model "
                                           "(operator decision)"},
            {"model": "Saaras V4", "reason": "not an analyst-answer model "
                                             "(operator decision)"}],
        "questions": [{"question_id": q.qid, "question": q.text,
                       "intent": list(q.intent), "oracle_kind":
                       q.oracle_kind} for q in bq.QUESTIONS],
    }
    path = OUT / "_runpod_suite.json"
    path.write_text(json.dumps(suite, indent=1, ensure_ascii=False) + "\n")
    return path


if __name__ == "__main__":
    if "--suite" not in sys.argv:
        main()
    print(write_suite())
