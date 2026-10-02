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
import hashlib
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hardware  # noqa: E402
import vllm_runtime as vr  # noqa: E402

PROFILES = ROOT / "profiles"
SUITE = PROFILES / "_runpod_suite.json"
DEFAULT_RUNTIME = ROOT / "artifacts" / "model_comparison" / "runtime"
HF = "https://huggingface.co"
A40_GB = 48.0                   # historical benchmark hardware
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
    if override or not src.get("repository") or src.get("identity_required"):
        ok, why, _ = verify_identity(repo, info, fetch, src)
        if not ok:
            return None, why
    elif (info.get("author") or repo.split("/")[0]) != repo.split("/")[0]:
        return None, f"{repo}: author {info.get('author')!r} differs"
    return repo, ""


def verify_identity(repo: str, info: dict, fetch: Fetch, src: dict
                    ) -> tuple[bool, str, dict[str, Any]]:
    """Live identity check before an immutable pin of a repository that was
    found by publisher + name (or named by the operator): the Hub's author
    is the repository's organisation, the repository is listed by that
    organisation, it has a model card at the pinned revision that names the
    model, and the card does not declare itself a re-upload of a same-named
    model elsewhere. Never accepted because a prompt or a note says so."""
    org, name = repo.split("/", 1)
    ev: dict[str, Any] = {"repository": repo, "revision": info.get("sha"),
                          "author": info.get("author"),
                          "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                      time.gmtime())}
    if info.get("author") != org:
        return False, (f"{repo}: Hub author {info.get('author')!r} is not "
                       f"the organisation {org!r}"), ev
    if info.get("disabled") or info.get("private"):
        return False, f"{repo}: disabled or private", ev
    pat = src.get("name_pattern")
    if pat and not re.match(pat, name, re.I):
        return False, f"{repo}: name does not match {pat!r}", ev
    exp = src.get("expected_repository")
    if exp and exp.lower() != repo.lower():
        return False, (f"{repo}: differs from the externally reported "
                       f"{exp}; operator decision needed"), ev
    try:
        listed = fetch(f"{HF}/api/models?author={urllib.parse.quote(org)}"
                       f"&limit=500")
        ev["listed_by_organisation"] = any(
            (h.get("id") or "").lower() == repo.lower() for h in listed or [])
    except Exception as exc:  # noqa: BLE001
        ev["listed_by_organisation"] = f"unverifiable: {exc}"
    if ev["listed_by_organisation"] is not True:
        return False, f"{repo}: not listed by organisation {org}", ev
    try:
        card = fetch(f"{HF}/{repo}/raw/{info['sha']}/README.md")
    except Exception as exc:  # noqa: BLE001
        return False, f"{repo}: no model card at {info['sha'][:12]} ({exc})", ev
    card = card if isinstance(card, str) else json.dumps(card)
    ev["model_card_sha256"] = hashlib.sha256(
        card.encode()).hexdigest()
    stem = re.sub(r"[-_.]", "", name.lower())
    if stem not in re.sub(r"[-_.\s]", "", card.lower()):
        return False, f"{repo}: model card does not name {name}", ev
    base = (info.get("cardData") or {}).get("base_model") or []
    base = [base] if isinstance(base, str) else list(base)
    reup = [b for b in base if b.split("/")[-1].lower() == name.lower()
            and b.lower() != repo.lower()]
    ev["base_model"] = base
    if reup:
        return False, (f"{repo}: card declares base_model {reup[0]} with "
                       f"the same name (a re-upload, not the original)"), ev
    ev["verdict"] = "VERIFIED"
    return True, "", ev


# ---- 2/3. pin + licence ---------------------------------------------------------

def _license(info: dict) -> str | None:
    card = info.get("cardData") or {}
    lic = card.get("license")
    if not lic:
        lic = next((t.split(":", 1)[1] for t in info.get("tags") or []
                    if t.startswith("license:")), None)
    return str(lic).lower() if lic else None


def pin(repo: str, fetch: Fetch, revision: str | None = None
        ) -> dict[str, Any]:
    info = fetch(f"{HF}/api/models/{repo}/revision/{revision}?blobs=true"
                 if revision else f"{HF}/api/models/{repo}?blobs=true")
    sha = info["sha"]
    if revision and sha != revision:
        raise ValueError(f"{repo}: asked for {revision}, got {sha}")
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
    template_source = "tokenizer_config.json" if template else None
    names = {f["rfilename"] for f in files}
    if not template and "chat_template.jinja" in names:
        try:
            got = fetch(f"{HF}/{repo}/resolve/{sha}/chat_template.jinja")
            template_text = got if isinstance(got, str) else ""
            template_source = "chat_template.jinja" if template_text else None
        except Exception:  # noqa: BLE001
            template_text = ""
    card = info.get("cardData") or {}
    licence_files = sorted(n for n in names
                           if re.match(r"(?i)^(LICEN[CS]E|COPYING)", n))
    return {
        "repository": repo, "revision": sha,
        "tokenizer_revision": sha,
        "tokenizer_files": [f["rfilename"] for f in files
                            if "tokenizer" in f["rfilename"]],
        "chat_template_present": bool(template_text),
        "chat_template_mentions_tools": "tool" in template_text.lower(),
        "chat_template_source": template_source,
        "chat_template_sha256": (hashlib.sha256(
            template_text.encode()).hexdigest() if template_text else None),
        "chat_template_markers": [m for m in vr.ALL_MARKERS
                                  if m in template_text],
        "license": lic,
        "license_status": ("LICENSE_OK" if lic in OSI else
                           "LICENSE_REVIEW_REQUIRED"),
        "license_evidence": {
            "card_license": card.get("license"),
            "license_name": card.get("license_name"),
            "license_link": card.get("license_link"),
            "hub_tags": [t for t in info.get("tags") or []
                         if t.startswith("license:")],
            "licence_files": [f"{HF}/{repo}/blob/{sha}/{n}"
                              for n in licence_files],
            "model_card": f"{HF}/{repo}/blob/{sha}/README.md",
            "policy": "LICENSE_OK only for a machine-readable OSI-style "
                      "licence id in the model card; anything else is "
                      "LICENSE_REVIEW_REQUIRED until "
                      "approve.py grant license:<profile-id>"},
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
        kv_bytes: int = 2, hw: dict[str, Any] | None = None
        ) -> dict[str, Any]:
    """The A40 methodology (hardware.fit); `hw` defaults to the historical
    A40, so the original A40 arithmetic is reproduced exactly."""
    return hardware.fit(p, context=context, max_output=max_output, hw=hw,
                        kv_bytes=kv_bytes)


def _fit_inputs(raw: dict, runtime: Path | None, pid: str,
                fetch: Fetch | None) -> dict[str, Any] | None:
    """What the fit needs, for a pin that already exists: recorded on the
    profile, else the full pin record on the volume, else re-read from the
    Hub AT THE PINNED REVISION (metadata only)."""
    art = raw.get("artifact") or {}
    if art.get("fit_inputs"):
        return art["fit_inputs"]
    prev = _previous_pin(runtime, pid)
    if prev and prev.get("config") and prev.get("weights_bytes"):
        return {k: prev.get(k) for k in ("config", "weights_bytes",
                                         "native_context")}
    if fetch is not None and art.get("repository") and art.get("revision"):
        try:
            got = pin(art["repository"], fetch, revision=art["revision"])
            return {k: got.get(k) for k in ("config", "weights_bytes",
                                            "native_context")}
        except Exception:  # noqa: BLE001
            return None
    return None


def _previous_pin(runtime: Path | None, pid: str) -> dict | None:
    if runtime is None:
        return None
    try:
        return json.loads((runtime / "pins" / f"{pid}.json").read_text()
                          ).get("pin")
    except (OSError, ValueError):
        return None


def apply_fits(raw: dict, inputs: dict | None, hw: dict[str, Any]
               ) -> dict[str, Any]:
    """Hardware-specific fit evidence on the profile:

    runpod.fit / runpod.resource_status   the A40 evidence, exactly as it
                                          was recorded (never rewritten)
    runpod.fit_by_hardware[<hw id>]       one entry per hardware, written
                                          once and then kept as evidence
    runpod.current_host                   this host's fit; it alone decides
                                          probe eligibility
    """
    rp = raw.setdefault("runpod", {})
    ctx = int(rp.get("max_model_len") or 32768)
    mo = int(raw.get("max_output_tokens") or 8192)
    fbh = rp.setdefault("fit_by_hardware", {})
    a40 = hardware.A40_ID
    if rp.get("fit") and a40 not in fbh:
        fbh[a40] = dict(rp["fit"]) | {
            "resource_status": rp.get("resource_status"),
            "hardware_id": a40,
            "source": "historical A40 evidence (preserved as recorded)"}
    if inputs is None:
        cur = {"computable": False, "fits": False,
               "resource_status": "FIT_NOT_COMPUTED",
               "hardware_id": hw["hardware_id"],
               "summary": "fit inputs unavailable for this pin"}
    else:
        cur = fit(inputs, context=ctx, max_output=mo, hw=hw)
    cur["source"] = ("computed for the current host" +
                     (" (hardware assumed: no detection recorded)"
                      if hw.get("assumed") else ""))
    cur["host"] = {k: hw.get(k) for k in (
        "gpu", "memory_total_mib", "vram_gb_for_fit", "usable_budget_gb",
        "driver_version", "host_cuda", "fit_method", "detected_at",
        "source")}
    if hw["hardware_id"] not in fbh:
        fbh[hw["hardware_id"]] = cur
    if a40 not in fbh and inputs is not None:
        fbh[a40] = fit(inputs, context=ctx, max_output=mo) | {
            "source": "computed (nominal A40 48 GB) for cross-hardware "
                      "comparison"}
    if not rp.get("fit") and a40 in fbh:        # first A40 evidence
        rp["fit"] = {k: v for k, v in fbh[a40].items() if k != "source"}
        rp["resource_status"] = fbh[a40]["resource_status"]
    rp["current_host"] = cur
    hist = (fbh.get(a40) or {}).get("resource_status")
    if cur["resource_status"].startswith("RESOURCE_BLOCKED"):
        raw["status"] = "BLOCKED_RESOURCE"
        raw["status_reason"] = f"{cur['resource_status']}: {cur['summary']}"
    else:
        raw["status"] = "NOT_INSTALLED"
        raw["status_reason"] = (
            f"pinned; {cur['resource_status']}"
            + ("" if cur.get("computable") else f" ({cur['summary']})")
            + (f"; historical {hist}" if hist and hw["hardware_id"] != a40
               else "") + "; probe pending")
    if cur.get("context"):
        raw["context_tokens"] = cur["context"]
    return cur


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
            repin: bool = False, hw: dict[str, Any] | None = None,
            runtime: Path | None = None) -> dict[str, Any]:
    hw = hw or hardware.current(runtime)
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
        # Its fit IS recomputed for the current host (evidence per hardware
        # is kept; the current host decides eligibility).
        inputs = _fit_inputs(raw, runtime, pid, fetch)
        if inputs and not art.get("fit_inputs"):
            art["fit_inputs"] = inputs
        cur = apply_fits(raw, inputs, hw)
        _write(pid, raw)
        prev = _previous_pin(runtime, pid)
        return rec | {"pin_status": "PINNED", "kept_existing_pin": True,
                      "pin": prev, "current_fit": cur,
                      "fit_by_hardware": rp.get("fit_by_hardware"),
                      "historical_a40_status": (rp.get("fit_by_hardware") or
                                                {}).get(hardware.A40_ID, {})
                      .get("resource_status"),
                      "repository": art.get("repository"),
                      "revision": art["revision"],
                      "license": art.get("license"),
                      "license_status": art.get("license_status"),
                      "parameters": art.get("parameters"),
                      "architecture": art.get("architecture"),
                      "native_context": art.get("native_context"),
                      "fit": cur,
                      "resource_status": cur["resource_status"],
                      "license_evidence": art.get("license_evidence")}
    repo, why = resolve(raw, fetch, override)
    if repo is None:
        art.update({"pin_status": "PIN_BLOCKED", "pin_reason": why})
        raw["status"] = "PIN_BLOCKED"
        raw["status_reason"] = why
        _write(pid, raw)
        return rec | {"pin_status": "PIN_BLOCKED", "reason": why}
    p = pin(repo, fetch)
    src = art.get("source") or {}
    if override or not src.get("repository") or src.get("identity_required"):
        p["identity"] = verify_identity(repo, fetch(
            f"{HF}/api/models/{repo}?blobs=true"), fetch, src)[2]
    inputs = {"config": p["config"], "weights_bytes": p["weights_bytes"],
              "native_context": p["native_context"]}
    if art.get("revision") and art["revision"] != p["revision"] and \
            (rp.get("fit") or rp.get("fit_by_hardware")):
        # evidence belongs to the revision it was computed for: kept, never
        # carried over to a different revision
        rp.setdefault("superseded_fits", []).append({
            "revision": art["revision"], "fit": rp.pop("fit", None),
            "resource_status": rp.pop("resource_status", None),
            "fit_by_hardware": rp.pop("fit_by_hardware", None)})
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
                                   for w in p["weights"]},
                "fit_inputs": inputs})
    if p.get("identity"):
        art["identity_verification"] = p["identity"]
    raw["registry_id"] = repo
    raw["endpoint"]["model"] = repo
    raw["licence"] = p["license"] or "UNDETERMINED"
    raw["provenance_status"] = "PINNED"
    raw["identity_source"] = (f"pinned {p['pinned_at']} by "
                              f"pin_and_probe_models.py")
    rp["served_model_name"] = repo
    rp["runtime"] = "vllm"
    rp["chat_template_present"] = p["chat_template_present"]
    rp["chat_template_mentions_tools"] = p["chat_template_mentions_tools"]
    for k in ("chat_template_markers", "chat_template_sha256",
              "chat_template_source"):
        rp[k] = p[k]
    art["license_evidence"] = p["license_evidence"]
    if rp.get("resource_status") and not rp.get("fit"):
        rp.pop("resource_status")     # a pre-pin estimate, not evidence
    f = apply_fits(raw, inputs, hw)
    _write(pid, raw)
    return rec | {"pin_status": "PINNED", "repository": repo,
                  "revision": p["revision"],
                  "license": p["license"],
                  "license_status": p["license_status"],
                  "parameters": p["parameters"],
                  "architecture": p["architecture"],
                  "native_context": p["native_context"],
                  "fit": f, "resource_status": f["resource_status"],
                  "current_fit": f,
                  "fit_by_hardware": rp.get("fit_by_hardware"),
                  "historical_a40_status": rp["fit_by_hardware"].get(
                      hardware.A40_ID, {}).get("resource_status"),
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


def assign_parsers(pid: str, runtime: Path, fetch: Fetch | None = None
                   ) -> dict[str, Any]:
    """Choose the tool parser from the family's registered candidates and
    the markers in the model's own chat template, and verify it against the
    parser registry of the INSTALLED vLLM when the runtime manifest exists
    (else the vLLM 0.30.0 source list, re-checked by the preflight)."""
    path = PROFILES / f"{pid}.json"
    raw = json.loads(path.read_text())
    rp, art = raw.setdefault("runpod", {}), raw.get("artifact") or {}
    markers = rp.get("chat_template_markers")
    if markers is None and art.get("revision") and fetch is not None and \
            not rp.get("template_from_mistral_common"):
        try:                       # an earlier pin predates marker capture
            got = pin(art["repository"], fetch)
            if got["revision"] == art["revision"]:
                markers = got["chat_template_markers"]
                for k in ("chat_template_markers", "chat_template_sha256",
                          "chat_template_source"):
                    rp[k] = got[k]
        except Exception:  # noqa: BLE001
            markers = None
    man = vr.load_manifest(runtime)
    parsers = (man or {}).get("parsers") or {}
    tool_reg = parsers.get("tool") or vr.STATIC_TOOL_PARSERS
    reason_reg = parsers.get("reasoning") or vr.STATIC_REASONING_PARSERS
    plan = vr.parser_plan(rp, markers, tool_reg, reason_reg)
    rp["tool_call_parser"] = plan["tool_call_parser"]
    rp["suggested_tool_call_parser"] = plan["tool_call_parser"]
    rp["parser_status"] = plan["status"]
    rp["parser_evidence"] = plan["evidence"] or plan["detail"]
    rp["parser_registry_source"] = ("installed vLLM (runtime manifest)"
                                    if parsers.get("tool") else
                                    "vLLM 0.30.0 source (unverified on host)")
    _write(pid, raw)
    return plan


def serve_and_probe(pid: str, runtime: Path, *, keep: bool = False
                    ) -> dict[str, Any]:
    """Serve, probe with the dummy tool, and stop (or keep, for the
    runner). No benchmark question is ever sent here. Every failure carries
    its own class (vllm_runtime.TAXONOMY); nothing is a generic failure."""
    from backend.model_lab import probe, registry

    raw = json.loads((PROFILES / f"{pid}.json").read_text())
    man = vr.load_manifest(runtime)
    if man and man["verdict"]["status"] != "COMPATIBLE":
        return {"probe_status": vr.HOST_DRIVER_INCOMPATIBLE,
                "failure": "; ".join(man["verdict"]["reasons"]) + " -- "
                           + man["verdict"]["remediation"]}
    if not (raw.get("runpod") or {}).get("suggested_tool_call_parser"):
        return {"probe_status": vr.TOOL_PARSER_MISSING,
                "failure": "no tool-call parser is assigned for this model: "
                           + str((raw.get("runpod") or {}).get(
                               "parser_evidence") or "no registered parser "
                               "for this family and no known tool-call "
                               "marker in its chat template")}
    gate = vr.profile_gate(man, pid)
    if gate:
        return gate
    srv = start_server(pid, runtime)
    kept = False
    try:
        why = wait_ready(srv)
        if why:
            log = Path(srv.log_path).read_text(errors="replace")[-20000:] \
                if Path(srv.log_path).exists() else ""
            cls = vr.classify_server_log(log)
            dl = vr.verify_download(
                (raw.get("artifact") or {}) | {"weights": _pinned_weights(
                    runtime, pid)},
                Path(os.environ.get("MODEL_CACHE_DIR", "")) if
                os.environ.get("MODEL_CACHE_DIR") else Path("/nonexistent"))
            if cls == vr.MODEL_DOWNLOAD_FAILED and dl["ok"]:
                cls = vr.MODEL_SERVER_START_FAILED   # the files are complete
            return {"probe_status": cls, "failure": why, "download": dl}
        prof = registry.load_profiles()[pid]
        res = probe.probe_profile(prof, base_url="http://127.0.0.1:8000/v1")
        probe.save(runtime, res)
        st = registry.readiness(prof, approvals=registry.load_approvals(
            runtime), probes={pid: res})
        ok = st.status == "READY_E2E"
        out = {"probe_status": "READY_E2E" if ok else
               vr.MODEL_TOOL_ROUNDTRIP_FAILED,
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


def _pinned_weights(runtime: Path, pid: str) -> list[dict]:
    p = runtime / "pins" / f"{pid}.json"
    try:
        return (json.loads(p.read_text()).get("pin") or {}).get("weights") \
            or []
    except (OSError, ValueError):
        return []


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
    hw = hardware.current(runtime)
    print(f"current host: {hw['hardware_id']} ({hw.get('gpu')}; "
          f"{hw.get('vram_gb_for_fit')} GB for fit; "
          f"{'ASSUMED' if hw.get('assumed') else hw.get('source')})")
    roster = []
    for pid in ids:
        try:
            rec = qualify(pid, fetch, override=overrides.get(pid),
                          repin=repin, hw=hw, runtime=runtime)
        except Exception as exc:  # noqa: BLE001 - record and continue
            rec = {"profile_id": pid, "pin_status": "PIN_BLOCKED",
                   "reason": f"{type(exc).__name__}: {exc}"[:400]}
        if rec.get("pin_status") == "PINNED":
            plan = assign_parsers(pid, runtime, fetch)
            rec["tool_call_parser"] = plan["tool_call_parser"]
            rec["reasoning_parser"] = plan["reasoning_parser"]
            rec["parser_status"] = plan["status"]
        approvals = registry.load_approvals(runtime)
        licence_ok = rec.get("license_status") == "LICENSE_OK" or \
            f"license:{pid}" in approvals
        blocked = str(rec.get("resource_status") or "").startswith(
            "RESOURCE_BLOCKED")
        rec["hardware_id"] = hw["hardware_id"]
        if do_probe and rec.get("pin_status") == "PINNED" and \
                not blocked and licence_ok:
            rec |= serve_and_probe(pid, runtime)
        elif do_probe:
            rec["probe_status"] = (
                vr.PIN_BLOCKED if rec.get("pin_status") != "PINNED" else
                vr.RESOURCE_BLOCKED if blocked
                else vr.LICENSE_REVIEW_REQUIRED)
            rec["probe_skipped_because"] = (
                rec.get("reason") or rec.get("resource_status")
                if rec.get("pin_status") != "PINNED" or blocked
                else "LICENSE_REVIEW_REQUIRED")
        if rec.get("license_status") == "LICENSE_REVIEW_REQUIRED" and \
                f"license:{pid}" not in approvals:
            ev = (rec.get("pin") or {}).get("license_evidence") or \
                rec.get("license_evidence") or {}
            print(f"  LICENSE_REVIEW_REQUIRED {pid}: licence "
                  f"{rec.get('license')!r} name={ev.get('license_name')!r} "
                  f"link={ev.get('license_link')!r} files="
                  f"{ev.get('licence_files')} card={ev.get('model_card')}")
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
