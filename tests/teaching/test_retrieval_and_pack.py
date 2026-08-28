"""
§16-§19 — what reaches a live prompt, and what it costs.

Two kinds of test, and the split is the same as the module's
--------------------------------------------------------------
The eligibility tests are about safety: a case that should never be shown, and
whether it is shown. A failure there is a leak.

The ranking tests are about usefulness: whether the right example comes first.
A failure there is a worse prompt.

They are kept apart because a good relevance score must never be able to
compensate for a failed filter, and a test file that mixes them invites exactly
that.
"""

from __future__ import annotations

import pytest

from backend.llm import caching as ca
from backend.llm import telemetry as tl
from backend.teaching import families as fam
from backend.teaching import pack as tp
from backend.teaching import retrieval as rv
from backend.teaching import schema as sc
from backend.teaching import status as st


def _case(case_id="tc-1", *, status=st.APPROVED, **over) -> sc.TeachingCase:
    base = dict(
        case_id=case_id, title="Total EAD by sector",
        family_id="SINGLE_DOMAIN_AGGREGATION",
        question="What is total exposure at default by sector?",
        objectives=[sc.Objective(id="o1", text="total EAD by sector")],
        analytical_plan_contract={"group_by": ["sector"]},
        concepts=["exposure at default"], operations=["SUM"],
        required_datasets=["portfolio_facility"], grain="facility",
        expected_capability="ANALYSIS",
        expected_conversation_action="NEW_REQUEST",
        ontology_version="2.0.0", cluster_id=f"cl-{case_id}",
    )
    base.update(over)
    case = sc.TeachingCase(**base)
    case.review_status = status
    return sc.sealed(case)


# ============================================================ eligibility


def test_only_approved_cases_are_eligible():
    cases = [_case("a", status=st.APPROVED), _case("b", status=st.DRAFT),
             _case("c", status=st.STALE), _case("d", status=st.REJECTED),
             _case("e", status=st.AUTO_VALIDATED)]
    kept, refused = rv.eligible(cases, rv.Need())
    assert [c.case_id for c in kept] == ["a"]
    assert sum(refused.values()) == 4


def test_a_stale_case_is_refused_however_relevant_it_is():
    """The point of the sweep. A case whose ontology moved is a case teaching
    a reading the ontology no longer has."""
    stale = _case("stale", status=st.STALE)
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS", concepts=("exposure at default",))
    assert rv.retrieve([stale], need).cases == []


def test_a_diagnostic_case_never_reaches_a_live_prompt():
    """§8: a diagnostic case may carry the exact values that validate a
    method, and those "remain evaluation and reference data and are never
    given to the live planner before execution"."""
    case = _case("diag", data_sensitivity=st.DIAGNOSTIC)
    kept, refused = rv.eligible([case], rv.Need())
    assert kept == []
    assert "not structure-only" in refused


def test_a_client_case_is_refused_before_its_status_is_even_read():
    case = _case("client", data_sensitivity=st.CLIENT)
    kept, refused = rv.eligible([case], rv.Need())
    assert kept == []
    assert any("client" in reason for reason in refused)


def test_anything_carrying_a_holdout_provenance_is_refused():
    """The seal is the basis of every accuracy claim in the product. The check
    is cheap and unconditional for the same reason a smoke alarm is."""
    case = _case("leak", source_provenance="holdout:HB-014")
    kept, refused = rv.eligible([case], rv.Need())
    assert kept == []
    assert "holdout source" in refused


def test_system_validated_cases_appear_only_where_governed():
    case = _case("sys", status=st.SYSTEM_VALIDATED)
    assert rv.eligible([case], rv.Need())[0] == []
    permitted = rv.Permission(system_validated=True)
    assert rv.eligible([case], rv.Need(), permission=permitted)[0] == [case]


def test_a_permission_that_names_families_restricts_to_them():
    cases = [_case("a", family_id="SINGLE_DOMAIN_AGGREGATION"),
             _case("b", family_id="AGENTIC_ORCHESTRATION")]
    permitted = rv.Permission(families=frozenset({"SINGLE_DOMAIN_AGGREGATION"}))
    kept, _ = rv.eligible(cases, rv.Need(), permission=permitted)
    assert [c.case_id for c in kept] == ["a"]


def test_a_difficulty_ceiling_is_enforced_and_fails_closed():
    """An unrecognised difficulty is treated as harder than any ceiling — the
    same shape as the assurance ceiling that let an unknown status through by
    ranking it weakest."""
    permitted = rv.Permission(max_difficulty=sc.INTERMEDIATE)
    assert rv.eligible([_case("a", difficulty=sc.EXPERT)],
                       rv.Need(), permission=permitted)[0] == []
    unknown = _case("b")
    unknown.difficulty = "EASY-ISH"
    assert rv.eligible([unknown], rv.Need(), permission=permitted)[0] == []


def test_a_refusal_says_which_filter_did_it():
    """A request that retrieves nothing is normal. The only way to tell a
    correct nothing from a broken one is to see which rule fired."""
    cases = [_case("a", status=st.DRAFT),
             _case("b", data_sensitivity=st.CLIENT),
             _case("c", source_provenance="holdout:x")]
    _, refused = rv.eligible(cases, rv.Need())
    assert len(refused) == 3


# ------------------------------------------------------- §48 scope safety


def test_a_retail_question_never_retrieves_a_corporate_only_case():
    corporate = _case("corp", portfolio_scope=fam.CORPORATE,
                      family_id="CORPORATE_SCOPE")
    need = rv.Need(portfolio_scope=fam.RETAIL)
    kept, refused = rv.eligible([corporate], need)
    assert kept == []
    assert "portfolio scope" in refused


def test_a_corporate_question_never_retrieves_a_retail_only_case():
    retail = _case("ret", portfolio_scope=fam.RETAIL, family_id="RETAIL_SCOPE")
    assert rv.eligible([retail], rv.Need(portfolio_scope=fam.CORPORATE))[0] \
        == []


def test_a_case_that_teaches_the_scope_violation_is_admitted():
    """§48's one exception, and it needs a marker a reviewer sets rather than
    a heuristic that guesses."""
    case = _case("x", portfolio_scope=fam.CORPORATE,
                 tags=[rv.SCOPE_VIOLATION_TAG])
    assert rv.eligible([case], rv.Need(portfolio_scope=fam.RETAIL))[0] == [case]


def test_a_scope_neutral_case_with_scope_specific_semantics_is_refused():
    """"Scope-neutral metadata cases may be used only where they contain no
    scope-specific data semantics." A case labelled NONE that names a retail
    product is a retail case whose scope field was left at the default."""
    sneaky = _case("x", portfolio_scope=fam.NO_SCOPE,
                   industry_or_product_scope="credit cards")
    assert rv.eligible([sneaky], rv.Need(portfolio_scope=fam.CORPORATE))[0] \
        == []
    assert rv.eligible([sneaky], rv.Need())[0] == [sneaky]


def test_a_case_in_another_language_is_not_retrieved():
    """§49: locale-aware now, so that Arabic cases cannot leak into English
    prompts the day Arabic is added."""
    arabic = _case("ar", language="ar")
    assert rv.eligible([arabic], rv.Need(language="en"))[0] == []
    assert rv.eligible([arabic], rv.Need(language="ar"))[0] == [arabic]


# ================================================================ ranking


def test_the_most_relevant_case_comes_first():
    right = _case("right", question="What is total exposure at default by "
                                    "sector?", cluster_id="cl-1")
    wrong = _case("wrong", question="What does DSCR mean?",
                  family_id="DATA_DICTIONARY", concepts=["net leverage"],
                  expected_capability="DATA_DICTIONARY", cluster_id="cl-2")
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS", concepts=("exposure at default",))
    result = rv.retrieve([wrong, right], need)
    assert result.entries[0].case_id == "right"


def test_the_entries_are_reported_in_the_order_they_rank():
    """The family decay is applied after sorting, so the order the scores were
    computed in is not the order they rank in. Reported out of order, a caller
    reading the top entry would not be reading the top case."""
    cases = [_case(f"c{i}", cluster_id=f"cl-{i}",
                   question=f"What is total exposure at default by sector {i}?")
             for i in range(5)]
    result = rv.retrieve(cases, rv.Need(question="total exposure at default "
                                                 "by sector",
                                        capability="ANALYSIS"))
    scores = [e.relevance_score for e in result.entries]
    assert scores == sorted(scores, reverse=True)
    assert [c.case_id for c in result.cases] == \
        [e.case_id for e in result.entries]


def test_at_most_five_cases_are_returned():
    cases = [_case(f"c{i}", cluster_id=f"cl-{i}") for i in range(20)]
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS", concepts=("exposure at default",))
    assert len(rv.retrieve(cases, need).cases) <= rv.MAX_CASES


def test_at_most_one_case_from_a_paraphrase_cluster():
    """§17. Five wordings of one question is one example repeated five
    times, and it crowds out the four the planner has not seen."""
    cases = [_case(f"c{i}", cluster_id="cl-same") for i in range(6)]
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS", concepts=("exposure at default",))
    result = rv.retrieve(cases, need)
    assert len(result.cases) == 1
    assert result.refused["duplicate cluster"] == 5


def test_an_irrelevant_question_retrieves_nothing():
    """§17: "Do not force irrelevant examples." An empty pack is a better
    prompt than a misleading one."""
    cases = [_case(f"c{i}", cluster_id=f"cl-{i}") for i in range(5)]
    result = rv.retrieve(cases, rv.Need(question="zxqv wibble frobnicate"))
    assert result.cases == []
    assert result.refused["below relevance floor"] == 5


def test_a_feature_the_need_did_not_declare_does_not_penalise_a_case():
    """The weighted average runs over what was asked for, not over all sixteen
    features. Otherwise a request that knows only its capability scores every
    case at one-sixteenth and everything falls under the floor."""
    case = _case("a")
    thin = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS")
    assert rv.retrieve([case], thin).cases == [case]


def test_the_output_says_which_features_matched():
    """§17's `matched_features` and `why_retrieved`. "The planner used a bad
    example" is unactionable; "it matched on family and nothing else" is a
    fix."""
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS", concepts=("exposure at default",),
                   grain="facility", datasets=("portfolio_facility",))
    entry = rv.retrieve([_case("a")], need).entries[0]
    assert set(entry.matched_features) >= {"capability", "concepts", "grain",
                                           "datasets"}
    assert entry.why_retrieved.startswith("matched on")


def test_the_output_carries_every_field_section_17_names():
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS")
    entry = rv.retrieve([_case("a")], need).entries[0].to_dict()
    assert set(entry) == {"case_id", "case_version", "relevance_score",
                          "matched_features", "why_retrieved",
                          "diversity_cluster", "estimated_tokens",
                          "approved_status", "ontology_version"}
    assert entry["estimated_tokens"] > 0
    assert entry["approved_status"] == st.APPROVED
    assert entry["ontology_version"] == "2.0.0"


def test_an_embedder_is_used_when_supplied_and_optional_when_not():
    class _Embedder:
        def embed(self, texts):
            # A degenerate embedder that likes the second case.
            return [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]

    cases = [_case("a", cluster_id="cl-a"), _case("b", cluster_id="cl-b")]
    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS")
    with_embeddings = rv.retrieve(cases, need, embedder=_Embedder())
    assert {e.case_id for e in with_embeddings.entries} == {"a", "b"}


def test_a_broken_embedder_does_not_break_retrieval():
    """An optional scorer that is down means the governed and lexical halves
    decide alone — which is the behaviour with no embedder at all."""
    class _Broken:
        def embed(self, texts):
            raise RuntimeError("the embedding service is down")

    need = rv.Need(question="What is total exposure at default by sector?",
                   capability="ANALYSIS")
    assert rv.retrieve([_case("a")], need, embedder=_Broken()).cases


def test_every_feature_section_16_names_has_a_weight():
    declared = set(rv.WEIGHTS)
    assert {"capability", "conversation_action", "family", "concepts",
            "objective_kinds", "domains", "datasets", "relationships",
            "grain", "period", "operations", "ambiguity", "discourse",
            "visualization", "route", "difficulty", "risk"} == declared


def test_concept_overlap_is_measured_against_what_was_asked_for():
    """A symmetric measure would prefer a thin case: one covering both
    requested concepts must score the same whether it mentions three others or
    none."""
    rich = _case("rich", concepts=["exposure at default", "expected credit "
                                   "loss", "ifrs 9 stage"], cluster_id="cl-r")
    exact = _case("exact", concepts=["exposure at default"], cluster_id="cl-e")
    need = rv.Need(concepts=("exposure at default",))
    assert rv.features(rich, need)["concepts"] == 1.0
    assert rv.features(exact, need)["concepts"] == 1.0


# ============================================================ teaching pack


def test_a_pack_carries_what_section_18_admits():
    pack = tp.make(_case("a"))
    assert set(pack.body) <= {name for name, _ in tp.INCLUDED} | {"thread"}
    assert "reading" in pack.body
    assert "objectives" in pack.body
    assert "plan" in pack.body


def test_a_pack_carries_nothing_section_18_excludes():
    case = _case("a", notes="an internal note", description="a long paragraph",
                 reviewer="Amal")
    body = tp.make(case).to_dict()
    for forbidden in tp.EXCLUDED:
        assert forbidden not in body
    assert "an internal note" not in str(body)
    assert "Amal" not in str(body)


def test_a_pack_carries_the_trap_as_well_as_the_shape():
    """A pack that shows only the right shape cannot distinguish it from a
    plausible substitute, which is the whole reason the cases record what
    their question is usually got wrong."""
    case = _case("a", scope_contract={"forbidden_behaviours":
                                      ["summing a ratio"]})
    assert tp.make(case).body["reading"]["must_not"] == ["summing a ratio"]


def test_a_diagnostic_case_does_not_become_a_pack():
    assert tp.make(_case("a", data_sensitivity=st.DIAGNOSTIC)) is None
    assert tp.make(_case("a", data_sensitivity=st.CLIENT)) is None


def test_a_figure_that_reached_a_pack_is_redacted():
    """The schema already refuses a figure on a structure-only case. This is
    the second lock, on the path where it would actually reach a model."""
    case = _case("a")
    case.result_contract = {"answer": "Contracting ECL is 8,563."}
    body = str(tp.make(case).to_dict())
    assert "8,563" not in body
    assert "[figure removed]" in body


def test_the_budget_drops_whole_packs_rather_than_truncating_one():
    """A worked example with its ending cut off teaches the beginning of a
    method, which is worse than one fewer example."""
    cases = [_case(f"c{i}") for i in range(10)]
    packs = tp.build(cases, budget=300)
    assert 0 < len(packs) < 10
    assert sum(p.estimated_tokens() for p in packs) <= 300
    for pack in packs:
        assert "reading" in pack.body


def test_a_thread_is_carried_only_when_there_is_one():
    """Repeating the question as a one-item thread spends budget saying what
    the question field already said."""
    single = tp.make(_case("a"))
    assert "thread" not in single.body

    threaded = _case("b", conversation_turns=[
        sc.Turn(turn_index=0, user_message="Show the five largest.",
                conversation_action="NEW_REQUEST",
                expected_answer_behavior="five rows"),
        sc.Turn(turn_index=1, user_message="Only Contracting.",
                conversation_action="MODIFY_PREVIOUS",
                expected_answer_behavior="narrow, do not re-rank")],
        question="Show the five largest.")
    assert len(tp.make(threaded).body["thread"]) == 2


def test_an_empty_field_is_dropped_rather_than_sent():
    """A budget spent on an empty object is a budget not spent on an
    invariant."""
    body = tp.make(_case("a")).body
    assert all(v not in ({}, [], "") for v in body.values())


def test_packs_render_as_structured_data():
    """The planner returns a structured document (§20). An example shown as
    prose teaches it that prose is an acceptable shape."""
    rendered = tp.render(tp.build([_case("a")]))
    assert rendered.strip().startswith("[")
    assert '"reading"' in rendered


# ============================================================ prompt caching


def test_the_stable_prefix_comes_first_and_carries_one_breakpoint():
    blocks = [ca.Block("question", "What is total EAD?"),
              ca.Block("ontology", "O" * 3000, cacheable=True),
              ca.Block("system_policy", "P" * 2000, cacheable=True)]
    composed = ca.compose(blocks)
    assert composed[0]["text"].startswith("P")
    assert composed[1]["text"].startswith("O")
    assert "cache_control" not in composed[0]
    assert composed[1]["cache_control"] == ca.EPHEMERAL
    assert "cache_control" not in composed[-1]


def test_a_sensitive_block_is_never_inside_the_cached_span():
    """Both halves of the rule matter. A sensitive block placed before the
    breakpoint is cached even though it carries no marker of its own, so it is
    refused a place in the prefix as well as a marker."""
    blocks = [ca.Block("system_policy", "P" * 5000, cacheable=True),
              ca.Block("ontology", "client rows", cacheable=True,
                       sensitive=True)]
    composed = ca.compose(blocks)
    marked = [b for b in composed if "cache_control" in b]
    assert len(marked) == 1
    assert marked[0]["text"].startswith("P")
    assert composed[-1]["text"] == "client rows"
    assert ca.refusals(blocks) == [
        "ontology: client-sensitive content is never cached (§19)"]


def test_a_block_that_is_not_a_stable_prefix_block_is_refused():
    blocks = [ca.Block("retrieved_cases", "x" * 5000, cacheable=True)]
    assert ca.refusals(blocks)
    assert all("cache_control" not in b for b in ca.compose(blocks))


def test_a_short_prefix_is_not_worth_a_cache_entry():
    """Below the floor a cache entry costs more to write than it saves."""
    blocks = [ca.Block("system_policy", "short", cacheable=True)]
    assert not ca.worth_caching(blocks)
    assert all("cache_control" not in b for b in ca.compose(blocks))


def test_the_plain_form_is_the_same_prompt():
    """A provider that cannot cache must see the identical prompt, or two
    deployments of one release answer differently."""
    blocks = [ca.Block("question", "Q"),
              ca.Block("system_policy", "P" * 4000, cacheable=True)]
    assert ca.plain(blocks) == "P" * 4000 + "\n\nQ"
    assert ca.plain(blocks) == "\n\n".join(
        b["text"] for b in ca.compose(blocks))


def test_the_prefix_identity_moves_when_the_prefix_does():
    first = [ca.Block("system_policy", "P" * 4000, cacheable=True)]
    second = [ca.Block("system_policy", "P" * 4000 + "!", cacheable=True)]
    assert ca.identity(first) != ca.identity(second)
    assert ca.identity(first) == ca.identity(list(first))


def test_the_identity_ignores_the_varying_tail():
    """A cache hit rate that collapsed because a prompt was edited is a
    different fact from one that collapsed because traffic changed. The
    identity has to move for the first and not the second."""
    stable = ca.Block("system_policy", "P" * 4000, cacheable=True)
    assert ca.identity([stable, ca.Block("question", "A")]) == \
        ca.identity([stable, ca.Block("question", "B")])


@pytest.mark.parametrize("raw,expected", [
    (None, 0),
    (object(), 0),
])
def test_cache_usage_is_read_defensively(raw, expected):
    """A provider that stops reporting cache usage must make the telemetry say
    zero, not raise inside a successful call."""
    assert ca.usage(raw)["cache_read_input_tokens"] == expected


def test_cache_telemetry_reports_tokens_and_never_prompt_content():
    """§19: expose cache-hit telemetry SAFELY. The whole point of caching is
    that a long prefix is reused; a surface that showed which prefix would be
    showing the prompt."""
    tl.record_success(provider="anthropic", model="m", purpose="reading",
                      latency_ms=5, input_tokens=200, output_tokens=10,
                      cache_read_tokens=8000, cache_prefix="abc123")
    summary = tl.cache_summary()
    assert summary["cache_read_tokens"] >= 8000
    assert 0 < summary["served_by_cache"] <= 1
    assert "abc123" in summary["prefixes"]
    assert "P" * 100 not in str(summary)
