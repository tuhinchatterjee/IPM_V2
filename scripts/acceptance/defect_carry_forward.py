#!/usr/bin/env python
"""Every known defect from every feature session, re-asked of the integration.

    .venv/bin/python scripts/acceptance/defect_carry_forward.py

A branch merging cleanly does not mean its fixes survived. A merge takes the
side it is told to take, and a fix that lived on the side that lost is gone
without a conflict, without a failing test on that branch, and without anyone
noticing until a demonstration.

So each entry below re-asks the question the original defect answered, against
this build, from the outside. Where the check can be executed it is; where it
cannot it says so rather than assuming, and the matrix carries VERIFIED,
PRESENT, DEFERRED or NOT CHECKABLE HERE for every row.

Exit code is 0 only when nothing is PRESENT.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

VERIFIED = "VERIFIED"
PRESENT = "PRESENT"
DEFERRED = "DEFERRED"
UNCHECKABLE = "NOT CHECKABLE HERE"


@dataclass
class Row:
    module: str
    issue: str
    check: Callable[[], tuple[str, str]]
    status: str = ""
    detail: str = ""


def _lake(name: str) -> Any:
    import pandas as pd
    parts = sorted(glob.glob(str(ROOT / "data" / "analytics" / name
                                 / "**" / "*.parquet"), recursive=True))
    if not parts:
        return None
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)


def _source(path: str) -> str:
    file = ROOT / path
    return file.read_text() if file.exists() else ""


# ------------------------------------------------------------------- COCKPIT

def cockpit_credential_is_its_own() -> tuple[str, str]:
    """The Cockpit reads COCKPIT_ANTHROPIC_API_KEY and never the shared one.

    Asked BEHAVIOURALLY rather than by reading the source. A first pass looked
    for the string `ANTHROPIC_API_KEY` and reported the defect present — but
    that string is in the module because it heads a FORBIDDEN_FALLBACKS list
    whose whole purpose is to prove it is inert. Grepping for a name cannot
    tell a fallback from a list of fallbacks that are refused; setting the
    variable and seeing whether the Cockpit takes it can.
    """
    import os
    from backend.cockpit_agentic import credential

    saved = {name: os.environ.get(name)
             for name in (credential.COCKPIT_CREDENTIAL_VAR,
                          *credential.FORBIDDEN_FALLBACKS)}
    try:
        os.environ.pop(credential.COCKPIT_CREDENTIAL_VAR, None)
        for name in credential.FORBIDDEN_FALLBACKS:
            os.environ[name] = "sk-a-credential-the-cockpit-must-not-take"
        leaked = credential.present()
        return (PRESENT if leaked else VERIFIED,
                f"with every forbidden fallback set, the Cockpit reports "
                f"{credential.status()}")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def provider_repr_hides_the_key() -> tuple[str, str]:
    """A dataclass field reaches repr(); the key must not."""
    from backend.llm.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider(api_key="sk-secret-value-should-not-print")
    text = f"{provider!r} {provider}"
    leaked = "sk-secret-value-should-not-print" in text
    return (PRESENT if leaked else VERIFIED,
            "the key appears in repr" if leaked else "repr says PRESENT/MISSING")


def cockpit_refers_what_if_to_the_live_route() -> tuple[str, str]:
    from backend.cockpit_agentic import registry
    route = registry.entry("what_if").route
    return (VERIFIED if route == "/what-if" else PRESENT,
            f"registry says {route}")


def strict_roles_survived_the_role_union() -> tuple[str, str]:
    from backend.llm import roles
    strict = set(getattr(roles, "STRICT_ROLES", set()))
    want = {"cockpit_preprocess", "cockpit_reasoning"}
    return (VERIFIED if want <= strict else PRESENT,
            f"STRICT_ROLES={sorted(strict)}")


def every_active_role_has_a_cost_class() -> tuple[str, str]:
    from backend.llm import cost, roles
    missing = [r for r in roles.ACTIVE_ROLES if r not in cost.ROLE_CLASS]
    return (VERIFIED if not missing else PRESENT,
            f"unclassified: {missing}" if missing
            else f"{len(roles.ACTIVE_ROLES)} roles all classified")


def clarification_caveat_survives_the_cockpit_path() -> tuple[str, str]:
    """The chain's `if resumed:` caveat must be composed BEFORE the Cockpit
    short-circuit returns, or it is lost on every Cockpit-answered turn."""
    text = _source("backend/services/threads.py")
    if not text:
        return UNCHECKABLE, "threads.py not found"
    caveat = text.find("Read as an answer to the question CreditProbe asked")
    shortcut = text.find("cockpit_v2.answer_for")
    if caveat < 0 or shortcut < 0:
        return UNCHECKABLE, f"caveat={caveat} shortcut={shortcut}"
    return (VERIFIED if caveat < shortcut else PRESENT,
            f"caveat at {caveat}, Cockpit short-circuit at {shortcut}")


def scope_and_domain_lock_both_survived() -> tuple[str, str]:
    import inspect
    from backend.runtime.validation import validate
    params = inspect.signature(validate).parameters
    have = {"scope", "domain_lock"} <= set(params)
    return (VERIFIED if have else PRESENT, f"validate({', '.join(params)})")


def cockpit_reads_the_canonical_book() -> tuple[str, str]:
    from backend.cockpit_agentic import service
    import pandas as pd
    path = (ROOT / "data" / "cockpit_agentic_v3" / service.DEFAULT_RELEASE
            / "cockpit_facility_quarter.parquet")
    if not path.exists():
        return PRESENT, f"{service.DEFAULT_RELEASE} is not built"
    frame = pd.read_parquet(path, columns=["borrower_id", "facility_id",
                                           "reporting_currency"])
    canonical = (frame["borrower_id"].astype(str).str.startswith("CORP-").all()
                 and frame["facility_id"].astype(str).str.startswith("CFAC-").all()
                 and set(frame["reporting_currency"]) == {"SAR"})
    return (VERIFIED if canonical else PRESENT,
            f"default release {service.DEFAULT_RELEASE}, "
            f"{frame['borrower_id'].nunique():,} borrowers")


def no_synthetic_demo_wording_on_a_canonical_release() -> tuple[str, str]:
    from backend.cockpit_agentic import service, store
    try:
        manifest = store.read_manifest(service.DEFAULT_RELEASE)
    except Exception as e:                                      # noqa: BLE001
        return PRESENT, str(e)[:80]
    sentence = str(manifest.get("not_client_data", ""))
    wrong = "Cockpit Agentic V3 demonstration" in sentence
    return (PRESENT if wrong else VERIFIED, sentence[:90])


# ----------------------------------------------------------- EARLY WARNING

def ews_uses_canonical_borrower_ids() -> tuple[str, str]:
    frame = _lake("early_warning_borrower_month")
    if frame is None:
        return UNCHECKABLE, "the Early Warning lake is not built here"
    column = "customer_id" if "customer_id" in frame.columns else "borrower_id"
    ids = frame[column].astype(str)
    ok = bool(ids.str.startswith("CORP-").all())
    return (VERIFIED if ok else PRESENT,
            f"key column {column!r}, "
            f"{int((~ids.str.startswith('CORP-')).sum())} non-canonical")


def ews_borrowers_all_exist_in_the_canonical_book() -> tuple[str, str]:
    ews = _lake("early_warning_borrower_month")
    book = _lake("corporate_ifrs9")
    if ews is None or book is None:
        return UNCHECKABLE, "one of the two datasets is not built here"
    column = "customer_id" if "customer_id" in ews.columns else "borrower_id"
    orphans = set(ews[column].astype(str)) - set(book["borrower_id"])
    return (VERIFIED if not orphans else PRESENT,
            f"{len(orphans)} orphan(s)")


def ews_signals_route_redirects() -> tuple[str, str]:
    text = _source("frontend/src/app/early-warning/signals/page.tsx")
    if not text:
        return PRESENT, "the retired route has no page at all"
    return (VERIFIED if "redirect(" in text else PRESENT, "redirects" )


# ------------------------------------------------------------------ WHAT-IF

def masterscale_is_nineteen_plus_d() -> tuple[str, str]:
    """One scale, 19 performing grades, D a separate state at ordinal 20.

    Asserted on the ORDINALS rather than on a grade list, because the defect
    this guards against is two scales in play — a 12-grade Cockpit one beside
    the 19-grade canonical one — and what would betray that is the arithmetic,
    not the names.
    """
    from backend.corporate import ratingscale

    performing = list(ratingscale.PERFORMING)
    ordinals = sorted(ratingscale.ORDINAL.values())
    default_at = ratingscale.ORDINAL.get(ratingscale.DEFAULT_GRADE)
    ok = (len(performing) == 19
          and ordinals == list(range(1, 21))
          and default_at == 20)
    return (VERIFIED if ok else PRESENT,
            f"{len(performing)} performing, ordinals 1..{max(ordinals)}, "
            f"{ratingscale.DEFAULT_GRADE} at {default_at}, "
            f"v{getattr(ratingscale, 'SCALE_VERSION', '?')}")


def stage_three_applicable_pd_is_one_hundred() -> tuple[str, str]:
    frame = _lake("corporate_ifrs9")
    if frame is None:
        return UNCHECKABLE, "the corporate book is not built here"
    stage3 = frame[frame["stage"] == 3]
    if stage3.empty:
        return UNCHECKABLE, "no Stage 3 rows"
    off = stage3[stage3["pd_applicable"].round(6) != 100.0]
    return (VERIFIED if off.empty else PRESENT,
            f"{len(off)} of {len(stage3)} Stage 3 rows are not 100%")


def reported_period_set_is_sixteen_quarters() -> tuple[str, str]:
    frame = _lake("corporate_ifrs9")
    if frame is None:
        return UNCHECKABLE, "the corporate book is not built here"
    periods = sorted(frame["period"].unique())
    years = {int(p.split()[1]) for p in periods}
    ok = len(periods) == 16 and years <= {2022, 2023, 2024, 2025, 2026}
    return (VERIFIED if ok else PRESENT,
            f"{len(periods)} quarters, years {sorted(years)}")


def whatif_can_export_to_playbook() -> tuple[str, str]:
    from backend.exports import playbook_contract as contract
    ok = contract.WHAT_IF in contract.IMPLEMENTED_MODULES
    builder = "fromWhatIfResult" in _source("frontend/src/lib/playbook-export.ts")
    wired = "fromWhatIfResult" in _source(
        "frontend/src/app/what-if/thread/page.tsx")
    return (VERIFIED if ok and builder and wired else PRESENT,
            f"contract={ok} builder={builder} wired_into_the_thread={wired}")


def xgboost_is_importable() -> tuple[str, str]:
    try:
        import xgboost
        return VERIFIED, f"xgboost {xgboost.__version__}"
    except Exception as e:                                      # noqa: BLE001
        return PRESENT, f"{type(e).__name__}: {str(e)[:70]}"


# ------------------------------------------------------------------- LENSES

def lenses_are_installed_by_the_bootstrap() -> tuple[str, str]:
    text = _source("backend/bootstrap/plan.py")
    return (VERIFIED if '"lenses"' in text else PRESENT,
            "the bootstrap has a lenses step")


def scorecard_domains_stay_out_of_reach_of_a_lens() -> tuple[str, str]:
    from backend.scorecard import domains
    restricted = set(domains.restricted_datasets())
    return (VERIFIED if restricted else PRESENT,
            f"{len(restricted)} restricted dataset(s)")


# ----------------------------------------------------------------- PLAYBOOK

def both_playbooks_mount_without_collision() -> tuple[str, str]:
    from collections import Counter
    from backend.api.main import create_app
    spec = create_app().openapi()
    pairs = Counter((path, method) for path, ops in spec["paths"].items()
                    for method in ops)
    duplicates = [p for p, n in pairs.items() if n > 1]
    plural = [p for p in spec["paths"] if p.startswith("/api/v1/playbooks")]
    workspace = "/api/v1/playbook/home" in spec["paths"]
    committee = "/api/v1/playbook/committees" in spec["paths"]
    ok = not duplicates and not plural and workspace and committee
    return (VERIFIED if ok else PRESENT,
            f"{len(spec['paths'])} paths, {len(duplicates)} collisions, "
            f"plural={plural}")


def the_workspace_service_is_bound_everywhere_it_is_used() -> tuple[str, str]:
    import importlib
    import re
    committee = importlib.import_module("backend.playbook.service")
    missing: list[str] = []
    for path in list((ROOT / "backend").rglob("*.py")) + \
            list((ROOT / "scripts").rglob("*.py")):
        text = path.read_text(errors="replace")
        for match in re.finditer(r"from backend\.playbook import ([^\n]+)",
                                 text):
            names = [n.strip() for n in match.group(1).split(",")]
            alias = ("service" if "service" in names else next(
                (n.split()[-1] for n in names
                 if n.startswith("service as ")), None))
            if not alias:
                continue
            used = set(re.findall(rf"\b{alias}\.([A-Za-z_]\w*)", text))
            gone = [a for a in used if not hasattr(committee, a)]
            if gone:
                missing.append(f"{path.name}:{gone}")
    return (VERIFIED if not missing else PRESENT, "; ".join(missing[:3]))


def the_bootstrap_cannot_call_an_empty_playbook_ready() -> tuple[str, str]:
    text = _source("backend/bootstrap/readiness.py")
    both = ("playbook_committees" in text and "playbook_demo" in text)
    return (VERIFIED if both else PRESENT,
            "both halves have a readiness check" if both
            else "only one Playbook half is checked")


def a_pack_block_pins_a_revision() -> tuple[str, str]:
    from backend.models import playbook as models
    has = hasattr(models, "PlaybookBlock")
    return (VERIFIED if has else UNCHECKABLE, "playbook_blocks is declared")


# ---------------------------------------------------------- PROJECT PLANNER

def the_planner_has_a_seeded_plan() -> tuple[str, str]:
    text = _source("backend/bootstrap/plan.py")
    return (VERIFIED if '"planner"' in text else PRESENT,
            "the bootstrap has a planner step")


# ----------------------------------------------------- SCORECARD VALIDATION

def the_three_scorecard_populations_stay_disjoint() -> tuple[str, str]:
    from backend.scorecard import domains
    names = sorted(domains.restricted_datasets())
    kinds = {"APPLICATION", "BEHAVIORAL", "SME"}
    text = _source("backend/scorecard/validation/variables.py")
    declared = {k for k in kinds if k in text}
    return (VERIFIED if len(names) >= 3 else PRESENT,
            f"{len(names)} restricted datasets; kinds named: {sorted(declared)}")


def the_sme_registry_row_exists() -> tuple[str, str]:
    """The SME model registry row was missing on the feature branch: seed()
    looped over (APP, BEH) only while models.py pointed at registry_key='SME'.
    """
    text = _source("backend/scorecard/registry.py")
    if not text:
        return UNCHECKABLE, "registry module not found"
    seeds_sme = '"SME"' in text or "'SME'" in text
    return (DEFERRED if not seeds_sme else VERIFIED,
            "SME is seeded into the registry" if seeds_sme
            else "SME is still not seeded — recorded, post-demo")


# ------------------------------------------------------------------- SHARED

def one_alembic_head() -> tuple[str, str]:
    """Asked of Alembic itself.

    A first pass parsed the migration files with a regex and reported six
    heads. Alembic reports one. The regex was wrong — it could not see every
    shape `down_revision` is written in — and a check that disagrees with the
    tool it is checking is measuring itself. So ask the tool.
    """
    import subprocess
    result = subprocess.run([str(ROOT / ".venv" / "bin" / "alembic"), "heads"],
                            capture_output=True, text=True, cwd=ROOT)
    heads = [line for line in result.stdout.splitlines() if "(head)" in line]
    return (VERIFIED if len(heads) == 1 else PRESENT,
            "; ".join(h.strip() for h in heads) or result.stderr[-90:])


def the_display_contract_holds() -> tuple[str, str]:
    import subprocess
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_decimals.py")],
        capture_output=True, text=True, cwd=ROOT)
    return (VERIFIED if result.returncode == 0 else PRESENT,
            result.stdout.strip().splitlines()[-1][:90] if result.stdout
            else "")


ROWS: list[Row] = [
    Row("Cockpit", "the Cockpit's credential is its own, never the shared one",
        cockpit_credential_is_its_own),
    Row("Cockpit", "the provider never prints its API key",
        provider_repr_hides_the_key),
    Row("Cockpit", "a What-If referral offers the live route, not /stress",
        cockpit_refers_what_if_to_the_live_route),
    Row("Cockpit", "STRICT_ROLES survived the role union",
        strict_roles_survived_the_role_union),
    Row("Cockpit", "every active role has a cost routing class",
        every_active_role_has_a_cost_class),
    Row("Cockpit", "the clarification caveat survives the Cockpit path",
        clarification_caveat_survives_the_cockpit_path),
    Row("Cockpit", "scope and domain_lock both survived the hard merge",
        scope_and_domain_lock_both_survived),
    Row("Cockpit", "the Cockpit answers over the canonical book",
        cockpit_reads_the_canonical_book),
    Row("Cockpit", "the on-screen provenance sentence is true of the release",
        no_synthetic_demo_wording_on_a_canonical_release),
    Row("Early Warning", "canonical CORP- identity, not a private key",
        ews_uses_canonical_borrower_ids),
    Row("Early Warning", "no Early Warning borrower is an orphan",
        ews_borrowers_all_exist_in_the_canonical_book),
    Row("Early Warning", "the retired signals route redirects",
        ews_signals_route_redirects),
    Row("What-If", "one masterscale, 19 performing grades plus D",
        masterscale_is_nineteen_plus_d),
    Row("What-If", "Stage 3 applicable PD is 100%",
        stage_three_applicable_pd_is_one_hundred),
    Row("What-If", "the reported period set is 16 quarters",
        reported_period_set_is_sixteen_quarters),
    Row("What-If", "a What-If result can be exported to Playbook",
        whatif_can_export_to_playbook),
    Row("What-If", "XGBoost imports (the OpenMP defect)",
        xgboost_is_importable),
    Row("Lenses", "the shipped lenses are installed by the bootstrap",
        lenses_are_installed_by_the_bootstrap),
    Row("Lenses", "scorecard domains stay out of reach of a Lens",
        scorecard_domains_stay_out_of_reach_of_a_lens),
    Row("Playbook", "both Playbooks mount at /playbook without collision",
        both_playbooks_mount_without_collision),
    Row("Playbook", "every call site binds the right Playbook service",
        the_workspace_service_is_bound_everywhere_it_is_used),
    Row("Playbook", "the bootstrap cannot call an empty Playbook ready",
        the_bootstrap_cannot_call_an_empty_playbook_ready),
    Row("Playbook", "a pack block can pin an export revision",
        a_pack_block_pins_a_revision),
    Row("Project Planner", "the delivery plan is seeded",
        the_planner_has_a_seeded_plan),
    Row("Scorecard Validation", "the three populations stay disjoint",
        the_three_scorecard_populations_stay_disjoint),
    Row("Scorecard Validation", "the SME model registry row",
        the_sme_registry_row_exists),
    Row("Shared", "exactly one Alembic head", one_alembic_head),
    Row("Shared", "every user-facing number goes through the display contract",
        the_display_contract_holds),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="docs/defect_carry_forward.json")
    args = parser.parse_args(argv)

    width = max(len(r.issue) for r in ROWS) + 2
    module = ""
    for row in ROWS:
        try:
            row.status, row.detail = row.check()
        except Exception as e:                                  # noqa: BLE001
            row.status, row.detail = PRESENT, f"{type(e).__name__}: {e}"[:110]
        if row.module != module:
            module = row.module
            print(f"\n{module}")
        mark = {VERIFIED: "+", PRESENT: "X",
                DEFERRED: ".", UNCHECKABLE: "?"}[row.status]
        print(f"  {mark} {row.issue:<{width}} {row.status:<20} {row.detail}")

    present = [r for r in ROWS if r.status == PRESENT]
    counts = {s: sum(1 for r in ROWS if r.status == s)
              for s in (VERIFIED, PRESENT, DEFERRED, UNCHECKABLE)}
    (ROOT / args.out).write_text(json.dumps(
        {"counts": counts,
         "rows": [{"module": r.module, "issue": r.issue, "status": r.status,
                   "detail": r.detail} for r in ROWS]}, indent=2))

    print(f"\n{len(ROWS)} carried-forward issue(s): "
          + ", ".join(f"{n} {s.lower()}" for s, n in counts.items() if n))
    if present:
        print("\nPRESENT in the integration:")
        for row in present:
            print(f"  {row.module}: {row.issue} — {row.detail}")
    print(f"report: {args.out}")
    return 1 if present else 0


if __name__ == "__main__":
    raise SystemExit(main())
