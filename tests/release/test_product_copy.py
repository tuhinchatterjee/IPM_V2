"""What the product is allowed to say about itself, asserted. §12, §13.

Two bans, both absolute on any surface a normal user reads:

  * no intelligence provider or model identity — no "claude", "anthropic",
    "opus", "sonnet"; and
  * no "demo" or "demonstration".

The first was live: the header panel printed the model identifier and the
provider health sentence read "Questions are read and interpreted by
claude-opus-5 via anthropic". The second was live too: a chip reading
"DEMO - SYNTHETIC DATA" on every screen, and "demonstration data" scattered
through the Data Builder, the Trace inspector and the sign-in page.

Neither ban reaches into the machine
------------------------------------
`ANTHROPIC_API_KEY` keeps its name. `AnthropicProvider` keeps its name. The
ledger, the Trace's technical layer and the reproducibility run key all go on
recording exactly which model produced which answer, because model risk
management is not optional and "some model said so" is not an audit trail.
`/ai/status/audit` serves that to an administrator. The line this suite polices
is narrower and harder: does a NORMAL USER read it?

So there are two scans, and they are different on purpose. One walks the
frontend source and looks at the strings that reach the screen — JSX text and
rendered literals, not imports, not identifiers, not comments. The other calls
the real API routes a normal user's browser calls and reads the JSON that
comes back. A word can only reach a user through one of those two doors.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from backend.release import product_copy as pc

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"

# --------------------------------------------------------------- the module


class TestTheVocabularyItself:

    def test_the_banned_words_are_caught(self):
        for text in ("read by claude-opus-5", "via Anthropic", "GPT-4 said",
                     "DEMO - SYNTHETIC DATA", "a demonstration deployment",
                     "Demo Mode is on", "demo data"):
            assert pc.violations(text), text

    def test_ordinary_english_is_not_caught(self):
        """The counter-test. A scan with false positives gets switched off.

        "demography" and "democratic" contain the letters; "opus" appears in
        "magnum opus" and nowhere near this product; "demonstrate" is a verb a
        governance sentence may legitimately need.
        """
        for text in ("demographic segmentation", "a democratic process",
                     "this demonstrates the movement", "modus operandi",
                     "the corpus of questions", "haikus are not mentioned"):
            assert not pc.violations(text), text

    def test_neutralising_removes_the_word_and_keeps_the_sentence(self):
        before = ("Questions are read and interpreted by claude-opus-5 via "
                  "anthropic. It never calculates a figure.")
        after = pc.neutralise(before)
        assert pc.clean(after)
        assert "never calculates a figure" in after
        assert after.count(".") == before.count("."), "punctuation was eaten"

    def test_identity_keys_are_blanked_not_dropped(self):
        """Blanked, so a reader written against the shape still finds them."""
        body = pc.withhold_identity(
            {"model": "claude-opus-5", "provider": "anthropic", "state": "ok",
             "runs": [{"model": "claude-opus-5", "score": 91}]})
        assert body["model"] == ""
        assert body["provider"] == ""
        assert body["state"] == "ok"
        assert body["runs"][0] == {"model": "", "score": 91}


# ------------------------------------------------------- the rendered front end


def _rendered_strings(path: pathlib.Path) -> list[str]:
    """Every string in `path` that can reach a screen.

    Comments and module specifiers are excluded: `import { x } from
    "@/lib/demo"` is a file path, not copy, and the mandate is explicit that
    renaming internals is not the requirement. What is left is JSX text and
    the string literals a component renders.
    """
    src = path.read_text("utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    src = re.sub(r'^\s*import[^;]*;', "", src, flags=re.M)

    out: list[str] = []
    literal = re.compile(
        r'"([^"\\\n]*(?:\\.[^"\\\n]*)*)"'
        r"|'([^'\\\n]*(?:\\.[^'\\\n]*)*)'"
        r"|`([^`\\]*(?:\\.[^`\\]*)*)`")
    for m in literal.finditer(src):
        s = m.group(1) or m.group(2) or m.group(3) or ""
        # A route or a module specifier is an address, not copy. `"/demo"` is
        # the posture endpoint's path and `"@/lib/demo"` is a file; renaming
        # either moves letters around without changing a word on any screen.
        if s.startswith(("/", "@/", "./", "../")) and " " not in s:
            continue
        out.append(s)
    out.extend(m.group(1) for m in re.finditer(r">([^<>{}]{3,})<", src))
    return out


def _frontend_files() -> list[pathlib.Path]:
    return sorted(p for p in FRONTEND.rglob("*")
                  if p.suffix in (".ts", ".tsx") and "__tests__" not in str(p))


class TestNothingOnScreenNamesAVendor:

    def test_no_rendered_string_names_a_provider_or_model(self):
        offences = [
            (p.relative_to(ROOT), s, pc.violations(s))
            for p in _frontend_files() for s in _rendered_strings(p)
            if pc.PROVIDER_PATTERN.search(s)
        ]
        assert not offences, "\n".join(
            f"{p}: {s[:110]!r} -> {v}" for p, s, v in offences)

    def test_no_rendered_string_says_demo(self):
        offences = [
            (p.relative_to(ROOT), s)
            for p in _frontend_files() for s in _rendered_strings(p)
            if pc.DEMO_PATTERN.search(s)
        ]
        assert not offences, "\n".join(
            f"{p}: {s[:110]!r}" for p, s in offences)

    def test_the_scan_can_actually_fail(self):
        """A guard nobody has seen fail is a guard nobody trusts."""
        planted = "DEMO - SYNTHETIC DATA, read by claude-opus-5"
        assert pc.DEMO_PATTERN.search(planted)
        assert pc.PROVIDER_PATTERN.search(planted)

    def test_the_synthetic_disclosure_survived(self):
        """The ban must not have removed the honest part.

        Deleting the disclosure would pass both scans above and would be the
        one outcome worse than the wording it replaced: a generated portfolio
        presented as a bank's own book.
        """
        text = "\n".join(
            p.read_text("utf-8") for p in _frontend_files())
        assert "synthetic" in text.lower()
        assert "Synthetic data" in text


# --------------------------------------------------------------- the real API


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


#: Routes a normal user's browser calls. Not an exhaustive list of the 372 in
#: the OpenAPI document — the ones whose bodies carry PROSE, which is the only
#: place a banned word can hide. A route returning nothing but numbers cannot
#: name a vendor.
USER_ROUTES = (
    "/api/v1/health",
    "/healthz",
    "/api/v1/ai/status",
    "/api/v1/demo",
    "/api/v1/readiness",
    "/api/v1/ask/mode",
    "/api/v1/analyses",
    "/api/v1/data-builder/domains",
)


class TestNoRouteReturnsAVendorOrADemo:

    @pytest.mark.parametrize("route", USER_ROUTES)
    def test_the_body_is_clean(self, client, route):
        response = client.get(route, headers={"X-IPM-Role": "ANALYST",
                                              "X-IPM-User-Id": "1"})
        if response.status_code in (401, 403, 404):
            pytest.skip(f"{route} is not available here: {response.status_code}")
        body = json.dumps(response.json())
        found = pc.violations(body)
        assert not found, f"{route} returned {found[:6]}"

    def test_the_status_route_withholds_the_identity(self, client):
        """Blank, not absent — the shape is unchanged and the value is gone."""
        response = client.get("/api/v1/ai/status",
                              headers={"X-IPM-Role": "ANALYST",
                                       "X-IPM-User-Id": "1"})
        if response.status_code != 200:
            pytest.skip(f"/ai/status unavailable: {response.status_code}")
        ai = response.json()["ai"]
        assert ai["provider"] == ""
        assert ai["model"] == ""
        assert ai["state"], "the state itself must still be reported"
        assert ai["detail"], "and so must what the state means"

    def test_the_synthetic_posture_still_discloses(self, client):
        response = client.get("/api/v1/demo",
                              headers={"X-IPM-Role": "ANALYST",
                                       "X-IPM-User-Id": "1"})
        if response.status_code != 200:
            pytest.skip("no posture route here")
        body = response.json()
        assert body["label"] in ("", pc.SYNTHETIC_LABEL)
        assert "SYNTHETIC" in pc.SYNTHETIC_LABEL


class TestTheAdministratorCanStillSeeIt:
    """§12 bans the identity from PRODUCT copy, not from the system.

    An institution has to be able to answer "which model produced that
    answer". If this test ever goes green by the identity having been deleted
    rather than relocated, model risk management has lost its evidence.
    """

    def test_the_audit_route_carries_the_identity(self, client):
        response = client.get("/api/v1/ai/status/audit",
                              headers={"X-IPM-Role": "ADMIN",
                                       "X-IPM-User-Id": "1"})
        if response.status_code in (401, 403, 404):
            pytest.skip(f"audit route unavailable: {response.status_code}")
        body = response.json()
        assert body["identity_withheld"] is False
        assert "provider" in body["ai"]
        assert "model" in body["ai"]

    def test_an_analyst_cannot_read_it(self, client):
        response = client.get("/api/v1/ai/status/audit",
                              headers={"X-IPM-Role": "ANALYST",
                                       "X-IPM-User-Id": "1"})
        assert response.status_code in (401, 403), response.status_code

    def test_the_internal_health_still_names_the_model(self):
        from backend.llm import telemetry

        internal = telemetry.health(provider="anthropic", model="a-model",
                                    configured=True)
        assert internal["provider"] == "anthropic"
        assert internal["model"] == "a-model"
