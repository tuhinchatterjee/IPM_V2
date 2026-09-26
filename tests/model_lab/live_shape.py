"""
A provider that returns what the FROZEN Anthropic adapter returns.

`backend/llm/anthropic_provider.py` hands the engine `assistant_blocks` as
Anthropic SDK objects (`TextBlock`, `ToolUseBlock`) and `tool_calls` as
dicts. The frozen `RunStore.save_messages` then persists those blocks with
`json.dumps(default=str)`, i.e. as repr STRINGS. The dict-shaped fixtures
never exercised that path; the live Opus comparison `cmp-f364d8b6901a` did.

This wraps the lab fixtures so that, through the real frozen engine:
  * assistant blocks are real SDK objects (reproduces defect 1);
  * the answer cites rows the way the frozen result packet publishes them,
    `r0`, `r1`, ... and includes a DERIVED claim (reproduces defect 2).

It is a test double of a transport shape, not a model; no network.
"""

from __future__ import annotations

from typing import Any

from anthropic.types import TextBlock, ToolUseBlock

from backend.model_lab.adapters.fixture import FixtureProvider, FixtureResult

COL = "stage2_ead_sar_mn"


def _row_id(rows: list[dict[str, Any]], sector: str) -> str:
    for i, r in enumerate(rows):
        if r.get("sector") == sector:
            return f"r{i}"
    return "r0"


class AnthropicShapedProvider:
    def __init__(self, behaviour: str, model: str = "claude-opus-5",
                 *, text_prefix: str = "Working on it.") -> None:
        self.inner = FixtureProvider(behaviour, model)
        self.model = model
        self.text_prefix = text_prefix

    def converse(self, **kw: Any) -> FixtureResult:
        res = self.inner.converse(**kw)
        calls = [dict(c) for c in res.tool_calls]
        for c in calls:
            if c["name"] == "finalize_response" and \
                    c["input"].get("disposition") == "answer" and \
                    self.inner.artifact:
                c["input"] = self._published_ids(c["input"])
        blocks: list[Any] = []
        if self.text_prefix and calls:
            blocks.append(TextBlock(type="text", text=self.text_prefix))
        for c in calls:
            blocks.append(ToolUseBlock(type="tool_use", id=c["id"],
                                       name=c["name"], input=c["input"]))
        if not calls and res.text:
            blocks.append(TextBlock(type="text", text=res.text))
        res.tool_calls = calls
        res.assistant_blocks = blocks        # SDK objects, as live
        return res

    def _published_ids(self, body: dict[str, Any]) -> dict[str, Any]:
        """Cite `rN` ids and add a derived total, as a live analyst does."""
        artifact, rows = self.inner.artifact
        body = dict(body)
        claims = []
        for claim in body.get("numeric_claims") or []:
            claim = dict(claim)
            ev = dict(claim.get("evidence") or {})
            _, _, sector = str(ev.get("row_key", "")).partition("=")
            ev["row_key"] = _row_id(rows, sector)
            claim["evidence"] = ev
            claims.append(claim)
        claims.append({"claim_id": "total", "unit": "SAR million",
                       "derivation": {"operation": "sum", "operands": [
                           {"artifact_id": artifact, "column_id": COL,
                            "rows": "all"}]}})
        body["numeric_claims"] = claims
        body["narrative"] = (body.get("narrative", "") +
                             " Across all sectors Stage 2 exposure totals "
                             "{{claim.total}}.")
        for cov in body.get("coverage") or []:
            for ref in cov.get("evidence_refs") or []:
                _, _, sector = str(ref.get("row_key", "")).partition("=")
                ref["row_key"] = _row_id(rows, sector)
        return body


def factory(behaviours: dict[str, str]):
    """provider_factory: profile id -> Anthropic-shaped behaviour."""
    from backend.model_lab.adapters import build_provider

    def make(profile):
        b = behaviours.get(profile.profile_id)
        return AnthropicShapedProvider(b) if b else build_provider(profile)
    return make
