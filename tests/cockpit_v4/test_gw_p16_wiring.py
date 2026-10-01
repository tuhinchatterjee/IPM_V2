"""P16 wiring: no shared object opens a dead route, and every link a
workspace surface builds lands on a page that reads what it is given.

Found by the P16 dead-route audit: Messages sent any object without a page
of its own to `/objects/{id}` (no such page); a shared definition's
`?version=N` was ignored; `/scenarios?domain=` was ignored; the object
Trace linked metrics with a parameter the catalogue does not read.

EVIDENCE LABEL: UNIT (real link builder and real source files); NO MODEL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.workspace import messages
from backend.workspace.objects import KINDS

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "src" / "app"


def _page_exists(href: str) -> bool:
    """True when `href`'s path resolves to a Next.js page (a `[param]`
    directory matches any one segment)."""
    path = href.split("?", 1)[0].strip("/")
    here = APP
    for seg in [s for s in path.split("/") if s]:
        if (here / seg).is_dir():
            here = here / seg
            continue
        dyn = [d for d in here.iterdir() if d.is_dir()
               and d.name.startswith("[")]
        if not dyn:
            return False
        here = dyn[0]
    return (here / "page.tsx").exists()


def _object(kind: str) -> dict:
    body = {"thread_id": "th-1", "issue_id": "iss-1", "metric_id": "M001",
            "lens_id": "lens-01", "alert_type": "breach", "entry": "workspace"}
    return {"kind": kind, "object_id": f"{KINDS[kind]}-x", "version": 3,
            "body": body}


@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("recipient", [True, False])
def test_every_shared_kind_opens_an_existing_page(kind, recipient):
    actions = messages._actions(_object(kind), recipient=recipient)
    opens = [a for a in actions if a["href"]]
    assert opens, kind
    for a in opens:
        assert not a["href"].startswith("/objects/"), (kind, a)
        assert _page_exists(a["href"]), (kind, a["href"])


def test_a_shared_definition_opens_at_its_shared_version():
    actions = messages._actions(_object("scenario"), recipient=True)
    assert actions[0]["href"].endswith("?version=3")
    detail = (ROOT / "frontend/src/components/scenarios/scenario-detail.tsx"
              ).read_text()
    assert re.search(r'get\("version"\)', detail), \
        "the detail page reads the version it is linked with"
    assert "readScenario(scenarioId, v)" in detail


def test_linked_query_parameters_are_read_by_their_pages():
    src = ROOT / "frontend/src/components"
    library = (src / "scenarios/scenario-library.tsx").read_text()
    assert 'get("domain")' in library
    trace = (src / "trace/object-trace.tsx").read_text()
    assert "/metrics?m=" in trace and "/metrics?metric=" not in trace
    catalogue = (src / "metrics/metric-catalogue.tsx").read_text()
    assert re.search(r'get\("m"\)', catalogue)
    issue = (src / "guided/issue-detail.tsx").read_text()
    assert 'get("driver")' in issue


def test_the_issue_card_has_no_decorative_controls():
    card = (ROOT / "frontend/src/components/guided/requires-attention.tsx"
            ).read_text()
    for testid in ("issue-investigate", "issue-open", "issue-save-cohort",
                   "issue-whatif", "issue-driver", "issue-nbq"):
        block = card[card.index(f'data-testid="{testid}"') - 900:
                     card.index(f'data-testid="{testid}"')]
        assert "onClick" in block, testid
    assert "/what-if?cohort=" in card and "&from=issue" in card
    assert "?driver=" in card
    assert "onAsk" not in card, "the never-passed onAsk branch is gone"
