"""
Pre-benchmark qualification on the RunPod pod: resolve, PIN, fit, probe.

    python scripts/model_lab/runpod/pin_and_probe_models.py           # pin+fit
    python scripts/model_lab/runpod/pin_and_probe_models.py --probe   # + probe
    python scripts/model_lab/runpod/pin_and_probe_models.py \\
        --profile qwen3.5-4b-runpod --probe
    python scripts/model_lab/runpod/pin_and_probe_models.py \\
        --repo ornith-1.5-9b-runpod=SomeOrg/Ornith-1.5-9B     # operator names it

For every profile in the RunPod suite (run order), independently -- a
failure is recorded and the next model continues:

1. RESOLVE the official artifact: the profile's exact repository, or the
   publisher organisation + name pattern, accepting exactly ONE match.
   Otherwise PIN_BLOCKED.
2. PIN the immutable commit sha (never "main"/"latest"), and record the
   tokenizer revision and chat template, the licence, the parameter count,
   the architecture, the native context, and the SHA-256 and size of every
   weight file.
3. LICENCE: OSI-style licences are LICENSE_OK. Anything else, or none,
   is LICENSE_REVIEW_REQUIRED: the model is not run until
   `approve.py grant license:<profile-id>`.
4. FIT on the A40 (48 GB): the actual weight bytes, the KV cache for the
   served context (from config.json), the runtime overhead and the output
   reservation. If it does not fit, the model is RESOURCE_BLOCKED_A40.
   Nothing is ever quantised silently: a quantised deployment is a separate
   profile (`<base>--awq-4bit`) with its own pin.
5. PROBE (--probe): serve with vLLM (downloads that pinned checkpoint), run
   the harmless dummy-tool capability probe (chat template, tool parser,
   forced tool use, round trip, stop-reason mapping), stop the server.
   READY_E2E or PROBE_FAILED, with the exact failure.

No benchmark question is ever sent. Results: profiles/<id>.json (the pin),
<runtime>/pins/<id>.json (full record), <runtime>/pins/ROSTER.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PROFILES = ROOT / "profiles"
SUITE = PROFILES / "_runpod_suite.json"
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"
HF = "https://huggingface.co"
A40_GB = 48.0
USABLE_FRACTION = 0.90          # vLLM gpu_memory_utilization
OVERHEAD_GB = 3.0               # CUDA context, graphs, activations
OSI = {"apache-2.0", "mit", "bsd-3-clause", "bsd-2-clause", "bsd",
       "cc-by-4.0", "mpl-2.0", "isc", "unlicense", "openrail"}

Fetch = Callable[[str], Any]


def http_fetch(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent":
                                               "creditprobe-model-lab"})
    token = os.environ.get("HF_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310
        data = r.read()
    try:
        return json.loads(data)
    except ValueError:
        return data.decode(errors="replace")


# ---- 1. resolve ----------------------------------------------------------------

def resolve(raw: dict, fetch: Fetch, override: str | None = None
            ) -> tuple[str | None, str]:
    src = (raw.get("artifact") or {}).get("source") or {}
    if override:
        repo = override
    elif src.get("repository"):
        repo = src["repository"]
    else:
        org, pat = src.get("org"), src.get("name_pattern")
        if not org or not pat:
            return None, ("publisher organisation unknown; name the official "
                          "repository with --repo")
        hits = fetch(f"{HF}/api/models?author={urllib.parse.quote(org)}"
                     f"&limit=200")
        names = [h["id"] for h in hits or []
                 if re.match(pat, h["id"].split("/", 1)[-1], re.I)]
        if len(names) != 1:
            return None, (f"{len(names)} repositories of {org} match "
                          f"{pat!r}: {names[:5]} -- need exactly one")
        repo = names[0]
    try:
        info = fetch(f"{HF}/api/models/{repo}?blobs=true")
    except Exception as exc:  # noqa: BLE001
        return None, f"{repo}: not reachable ({type(exc).__name__}: {exc})"
    if not isinstance(info, dict) or not info.get("sha"):
        return None, f"{repo}: no immutable revision returned"
    return repo, ""


# ---- 2/3. pin + licence ---------------------------------------------------------

def _license(info: dict) -> str | None:
    card = info.get("cardData") or {}
    lic = card.get("license")
    if not lic:
        lic = next((t.split(":", 1)[1] for t in info.get("tags") or []
                    if t.startswith("license:")), None)
    return str(lic).lower() if lic else None


def pin(repo: str, fetch: Fetch) -> dict[str, Any]:
    info = fetch(f"{HF}/api/models/{repo}?blobs=true")
    sha = info["sha"]
    files = info.get("siblings") or []
    weights = [{"file": f["rfilename"], "bytes": f.get("size"),
                "sha256": (f.get("lfs") or {}).get("sha256")}
               for f in files if f["rfilename"].endswith(
                   (".safetensors", ".bin", ".gguf", ".pt"))]
    def cfg(name: str) -> dict:
        try:
            got = fetch(f"{HF}/{repo}/resolve/{sha}/{name}")
            return got if isinstance(got, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    config = cfg("config.json")
    tok = cfg("tokenizer_config.json")
    text = config.get("text_config") or config
    lic = _license(info)
    template = tok.get("chat_template")
    template_text = (json.dumps(template) if template else "")
    return {
        "repository": repo, "revision": sha,
        "tokenizer_revision": sha,
        "tokenizer_files": [f["rfilename"] for f in files
                            if "tokenizer" in f["rfilename"]],
        "chat_template_present": bool(template),
        "chat_template_mentions_tools": "tool" in template_text.lower(),
        "license": lic,
        "license_status": ("LICENSE_OK" if lic in OSI else
                           "LICENSE_REVIEW_REQUIRED"),
        "parameters": (info.get("safetensors") or {}).get("total"),
        "architecture": config.get("architectures") or
        [config.get("model_type")],
        "native_context": text.get("max_position_embeddings"),
        "config": {k: text.get(k) for k in (
            "num_hidden_layers", "num_attention_heads",
            "num_key_value_heads", "head_dim", "hidden_size",
            "torch_dtype")} | {"quantization_config":
                               config.get("quantization_config")},
        "weights": weights,
        "weights_bytes": sum(w["bytes"] or 0 for w in weights),
        "last_modified": info.get("lastModified"),
        "pinned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ---- 4. fit ----------------------------------------------------------------------

def fit(p: dict[str, Any], *, context: int, max_output: int,
        kv_bytes: int = 2) -> dict[str, Any]:
    c = p["config"]
    layers = c.get("num_hidden_layers") or 0
    heads = c.get("num_attention_heads") or 0
    kv_heads = c.get("num_key_value_heads") or heads
    head_dim = c.get("head_dim") or ((c.get("hidden_size") or 0) //
                                     max(1, heads))
    native = p.get("native_context") or context
    ctx = min(context, native)
    per_token = 2 * layers * kv_heads * head_dim * kv_bytes
    weights_gb = p["weights_bytes"] / 1e9
    kv_gb = per_token * ctx / 1e9
    total = weights_gb + kv_gb + OVERHEAD_GB
    budget = A40_GB * USABLE_FRACTION
    known = bool(layers and kv_heads and head_dim and p["weights_bytes"])
    ok = known and total <= budget and max_output < ctx
    return {"weights_gb": round(weights_gb, 2), "kv_cache_gb": round(kv_gb, 2),
            "kv_bytes_per_token": per_token, "context": ctx,
            "native_context": native, "output_reservation": max_output,
            "runtime_overhead_gb": OVERHEAD_GB,
            "total_gb": round(total, 2), "budget_gb": round(budget, 2),
            "fits": ok, "computable": known,
            "summary": (f"weights {weights_gb:.1f} GB + KV {kv_gb:.1f} GB "
                        f"({ctx} tokens) + overhead {OVERHEAD_GB} GB = "
                        f"{total:.1f} GB vs {budget:.1f} GB usable")
            if known else "config.json/weights incomplete: fit not computed"}


# ---- apply -------------------------------------------------------------------------

def _write(pid: str, raw: dict) -> None:
    text = json.dumps(raw, indent=1, ensure_ascii=False) + "\n"
    (PROFILES / f"{pid}.json").write_text(text)
    # On RunPod the source tree is Pod-local; the pinned identity is also
    # kept on the persistent volume so a new Pod resumes on the SAME exact
    # revisions (RUNPOD_BOOTSTRAP.sh restores it after unpacking).
    keep = os.environ.get("MODEL_LAB_PINNED_PROFILES_DIR")
    if keep:
        Path(keep).mkdir(parents=True, exist_ok=True)
        tmp = Path(keep) / f".{pid}.json.part"
        tmp.write_text(text)
        os.replace(tmp, Path(keep) / f"{pid}.json")


def qualify(pid: str, fetch: Fetch, *, override: str | None = None,
            repin: bool = False) -> dict[str, Any]:
    path = PROFILES / f"{pid}.json"
    raw = json.loads(path.read_text())
    art, rp = raw["artifact"], raw["runpod"]
    rec: dict[str, Any] = {"profile_id": pid,
                           "parent_profile_id": raw.get("parent_profile_id"),
                           "quantization": art.get("quantization")}
    if art.get("pin_status") == "PINNED" and art.get("revision") and \
            not override and not repin:
        # An existing pin is never re-resolved silently: a resumed suite
        # keeps the exact revision it started with (--repin to change).
        _write(pid, raw)
        return rec | {"pin_status": "PINNED", "kept_existing_pin": True,
                      "repository": art.get("repository"),
                      "revision": art["revision"],
                      "license": art.get("license"),
                      "license_status": art.get("license_status"),
                      "parameters": art.get("parameters"),
                      "architecture": art.get("architecture"),
                      "native_context": art.get("native_context"),
                      "fit": rp.get("fit"),
                      "resource_status": rp.get("resource_status")}
    repo, why = resolve(raw, fetch, override)
    if repo is None:
        art.update({"pin_status": "PIN_BLOCKED", "pin_reason": why})
        raw["status"] = "PIN_BLOCKED"
        raw["status_reason"] = why
        _write(pid, raw)
        return rec | {"pin_status": "PIN_BLOCKED", "reason": why}
    p = pin(repo, fetch)
    f = fit(p, context=int(rp.get("max_model_len") or 32768),
            max_output=int(raw.get("max_output_tokens") or 8192))
    art.update({"repository": repo, "revision": p["revision"],
                "tokenizer_revision": p["tokenizer_revision"],
                "pin_status": "PINNED", "pin_reason": "",
                "license": p["license"],
                "license_status": p["license_status"],
                "parameters": p["parameters"],
                "architecture": p["architecture"],
                "native_context": p["native_context"],
                "weights_bytes": p["weights_bytes"],
                "weights_sha256": {w["file"]: w["sha256"]
                                   for w in p["weights"]}})
    raw["registry_id"] = repo
    raw["endpoint"]["model"] = repo
    raw["licence"] = p["license"] or "UNDETERMINED"
    raw["provenance_status"] = "PINNED"
    raw["identity_source"] = (f"pinned {p['pinned_at']} by "
                              f"pin_and_probe_models.py")
    rp["served_model_name"] = repo
    rp["fit"] = f
    rp["runtime"] = "vllm"
    rp["chat_template_present"] = p["chat_template_present"]
    rp["chat_template_mentions_tools"] = p["chat_template_mentions_tools"]
    if f["computable"] and not f["fits"]:
        rp["resource_status"] = "RESOURCE_BLOCKED_A40"
        raw["status"] = "BLOCKED_RESOURCE"
        raw["status_reason"] = f"RESOURCE_BLOCKED_A40: {f['summary']}"
    else:
        rp["resource_status"] = ("FITS_A40" if f["fits"] else
                                 "FIT_NOT_COMPUTED")
        raw["status"] = "NOT_INSTALLED"
        raw["status_reason"] = ("pinned; " + ("fits the A40" if f["fits"]
                                              else f["summary"])
                                + "; probe pending")
    raw["context_tokens"] = f["context"]
    _write(pid, raw)
    return rec | {"pin_status": "PINNED", "repository": repo,
                  "revision": p["revision"],
                  "license": p["license"],
                  "license_status": p["license_status"],
                  "parameters": p["parameters"],
                  "architecture": p["architecture"],
                  "native_context": p["native_context"],
                  "fit": f, "resource_status": rp["resource_status"],
                  "chat_template_present": p["chat_template_present"],
                  "pin": p}


# ---- 5. probe ----------------------------------------------------------------------

def start_server(pid: str, runtime: Path) -> subprocess.Popen:
    log = runtime / "logs" / f"vllm_{pid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    srv = subprocess.Popen([str(ROOT / "scripts/model_lab/runpod/serve.sh"),
                            pid], stdout=log.open("wb"),
                           stderr=subprocess.STDOUT, cwd=ROOT,
                           start_new_session=True)
    srv.log_path = str(log)  # type: ignore[attr-defined]
    return srv


def wait_ready(srv: subprocess.Popen, wait_s: int = 1800) -> str:
    base = "http://127.0.0.1:8000/v1"
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if srv.poll() is not None:
            return f"vLLM exited rc={srv.returncode}; see {srv.log_path}"
        try:
            urllib.request.urlopen(base + "/models", timeout=5)  # noqa: S310
            return ""
        except Exception:  # noqa: BLE001
            time.sleep(5)
    return f"vLLM not ready after {wait_s}s; see {srv.log_path}"


def stop_server(srv: subprocess.Popen) -> None:
    try:
        os.killpg(srv.pid, 15)
        srv.wait(60)
    except subprocess.TimeoutExpired:
        os.killpg(srv.pid, 9)
    except ProcessLookupError:
        pass


def serve_and_probe(pid: str, runtime: Path, *, keep: bool = False
                    ) -> dict[str, Any]:
    """Serve, probe with the dummy tool, and stop (or keep, for the
    runner). No benchmark question is ever sent here."""
    from backend.model_lab import probe, registry

    raw = json.loads((PROFILES / f"{pid}.json").read_text())
    if not (raw.get("runpod") or {}).get("suggested_tool_call_parser"):
        return {"probe_status": "PROBE_FAILED",
                "failure": "no tool-call parser is configured for this "
                           "family: check the model card's documented tool "
                           "format, set runpod.suggested_tool_call_parser, "
                           "then re-run with --probe"}
    srv = start_server(pid, runtime)
    kept = False
    try:
        why = wait_ready(srv)
        if why:
            return {"probe_status": "PROBE_FAILED", "failure": why}
        prof = registry.load_profiles()[pid]
        res = probe.probe_profile(prof, base_url="http://127.0.0.1:8000/v1")
        probe.save(runtime, res)
        st = registry.readiness(prof, approvals=registry.load_approvals(
            runtime), probes={pid: res})
        ok = st.status == "READY_E2E"
        out = {"probe_status": "READY_E2E" if ok else "PROBE_FAILED",
               "readiness": st.status, "failure": "" if ok else
               "; ".join(st.reasons) + (f" | {res.get('error')}"
                                        if res.get("error") else ""),
               "controls": res.get("controls"), "vram_after_load_mib":
               _gpu_mem()}
        if ok and keep:
            out["_server"] = srv
            kept = True
        return out
    finally:
        if not kept:
            stop_server(srv)


def _gpu_mem() -> int | None:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10)
        return int(out.stdout.split()[0])
    except Exception:  # noqa: BLE001
        return None


# ---- roster ------------------------------------------------------------------------

def suite_profiles() -> list[str]:
    suite = json.loads(SUITE.read_text())
    return [m["profile_id"] for m in suite["models"]]


def run(ids: list[str], fetch: Fetch, runtime: Path, *, do_probe: bool,
        overrides: dict[str, str], repin: bool = False
        ) -> list[dict[str, Any]]:
    from backend.model_lab import registry

    out_dir = runtime / "pins"
    out_dir.mkdir(parents=True, exist_ok=True)
    roster = []
    for pid in ids:
        try:
            rec = qualify(pid, fetch, override=overrides.get(pid),
                          repin=repin)
        except Exception as exc:  # noqa: BLE001 - record and continue
            rec = {"profile_id": pid, "pin_status": "PIN_BLOCKED",
                   "reason": f"{type(exc).__name__}: {exc}"[:400]}
        approvals = registry.load_approvals(runtime)
        licence_ok = rec.get("license_status") == "LICENSE_OK" or \
            f"license:{pid}" in approvals
        if do_probe and rec.get("pin_status") == "PINNED" and \
                rec.get("resource_status") != "RESOURCE_BLOCKED_A40" and \
                licence_ok:
            rec |= serve_and_probe(pid, runtime)
        elif do_probe:
            rec["probe_status"] = "NOT_PROBED"
            rec["probe_skipped_because"] = (
                rec.get("reason") or rec.get("resource_status")
                if rec.get("pin_status") != "PINNED" or rec.get(
                    "resource_status") == "RESOURCE_BLOCKED_A40"
                else "LICENSE_REVIEW_REQUIRED")
        (out_dir / f"{pid}.json").write_text(json.dumps(rec, indent=1,
                                                        default=str))
        roster.append({k: v for k, v in rec.items() if k != "pin"})
        print(f"{pid:32} {rec.get('pin_status'):12} "
              f"{str(rec.get('license_status') or ''):24} "
              f"{str(rec.get('resource_status') or ''):22} "
              f"{rec.get('probe_status', '')}  "
              f"{(rec.get('revision') or rec.get('reason') or '')[:48]}")
    (out_dir / "ROSTER.json").write_text(json.dumps(
        {"generated_at": time.time(), "roster": roster}, indent=1,
        default=str))
    return roster


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--profile", action="append")
    ap.add_argument("--repo", action="append", default=[],
                    help="PROFILE=OWNER/REPO: operator names the official "
                         "repository for a profile that cannot be resolved")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--repin", action="store_true",
                    help="re-resolve revisions even for already pinned "
                         "profiles (operator decision; changes identities)")
    ap.add_argument("--runtime-dir", default=os.environ.get(
        "MODEL_LAB_RUNTIME_DIR", str(DEFAULT_RUNTIME)))
    args = ap.parse_args(argv)
    os.environ.setdefault("COCKPIT_AGENTIC_V3_NAMESPACE", "cockpit_v4")
    overrides = dict(x.split("=", 1) for x in args.repo)
    ids = args.profile or suite_profiles()
    run(ids, http_fetch, Path(args.runtime_dir).expanduser().resolve(),
        do_probe=args.probe, overrides=overrides, repin=args.repin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
