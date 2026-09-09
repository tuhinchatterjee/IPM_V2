"""
CreditProbe explaining itself, and the reconciliation that keeps it honest.

The defect
----------
    "What is CreditProbe AI?"

    "CreditProbe has no governed data about CreditProbe AI. It answers only
     from the datasets a steward has published…"

A true statement about the borrower book and the worst possible answer to the
question. The product is not a dataset, and a question about it must never be
answered by looking for one.

The other half of this suite is the part that matters in a year's time. A
product explanation is prose, and prose about software rots: a capability is
removed, the answer still describes it, and the answer is now a confident lie.
So the reconciliation tests fail the build when the registry and the running
system disagree — a signal family the engine evaluates and the methodology does
not mention, a dataset count that has moved, a capability naming an area the
feature matrix no longer has.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.product import answers as pa
from backend.product import knowledge as pk
from backend.product import methodology as me
from backend.product import routing as pr

# --------------------------------------------------------------------------
# The exact questions §20 requires, and which side of the line each falls
# --------------------------------------------------------------------------

PRODUCT_QUESTIONS: tuple[str, ...] = (
    "What is CreditProbe AI?",
    "What can CreditProbe do?",
    "What are all the features of CreditProbe?",
    "Explain every major CreditProbe module.",
    "Explain every major CreditProbe capability and why it matters to a "
    "corporate credit risk team.",
    "Why is CreditProbe useful to a credit risk officer?",
    "How can CreditProbe help a corporate credit risk team?",
    "What makes CreditProbe different from a normal dashboard?",
    "What does CreditProbe do that a traditional BI dashboard cannot?",
    "How does CreditProbe help a CRO?",
    "Why is Borrower 360 useful?",
    "Why is Early Warning useful?",
    "What does Data Builder do?",
    "What is Analysis Studio?",
    "What is Trace and Lineage?",
    "What does Scorecard Validation do?",
    "What is the role of AI in CreditProbe?",
    "How is AI leveraged in CreditProbe?",
    "How does CreditProbe use AI?",
    "What does Agentic AI do?",
    "What does the system engine do?",
    "What does the governed CreditProbe engine do?",
    "What is the CreditProbe Early Warning methodology?",
    "How does CreditProbe identify early deterioration?",
    "What is the four-layer Early Warning methodology?",
    "Explain the four layers of Early Warning.",
    "What is TAC?",
    "What is TAC methodology?",
    "What signals are used?",
    "What signals are used for liquidity risk?",
    "How often are the Early Warning signals collected?",
    "How frequently is each signal collected?",
    "How does an Early Warning signal become a Risk Case?",
    "How does a signal become a case?",
    "What does a persistent warning mean?",
    "Why is Early Warning valuable to a credit risk officer?",
)

DATA_QUESTIONS: tuple[str, ...] = (
    "Which borrowers are deteriorating?",
    "Which Shipping borrowers have rising utilisation, worsening liquidity "
    "and increasing 12-month PD?",
    "Which customers were downgraded and had expected credit loss rise in "
    "Q1 2026?",
    "What is total exposure at default by sector?",
    "Show the top 20 borrowers by 12-month PD.",
    "How many borrowers are in Stage 2?",
    "Which borrowers are on the Early Warning list?",
    "Which signals are firing for SA-100014?",
    "What is the average ECL in Q2 2026?",
)


class TestSelfKnowledgeRouting:
    """Which questions reach the product layer, and which never may."""

    @pytest.mark.parametrize("question", PRODUCT_QUESTIONS)
    def test_a_product_question_reaches_product_knowledge(
            self, question: str) -> None:
        intent = pr.read(question)
        assert intent.is_product, (
            f"{question!r} was routed to the borrower-data planner, which is "
            f"how it came back as 'no governed data about CreditProbe' "
            f"({intent.why})")
        assert intent.tool, "no product tool was chosen"

    @pytest.mark.parametrize("question", DATA_QUESTIONS)
    def test_a_data_question_never_reaches_product_knowledge(
            self, question: str) -> None:
        # The opposite failure, and the worse one: answering a portfolio
        # question with a product description.
        intent = pr.read(question)
        assert not intent.is_product, (
            f"{question!r} was answered from the product registry instead of "
            f"from the book ({intent.why})")

    @pytest.mark.parametrize("question", PRODUCT_QUESTIONS)
    def test_every_product_question_produces_a_real_answer(
            self, question: str) -> None:
        found = pr.answer(question)
        assert found is not None
        said = found.text()
        assert len(said) > 400, f"{question!r} produced a stub"
        assert "no governed data about CreditProbe" not in said

    @pytest.mark.parametrize("question", PRODUCT_QUESTIONS)
    def test_no_product_answer_proposes_a_chart(self, question: str) -> None:
        # §19. A product or methodology explanation has no quantitative shape.
        found = pr.answer(question)
        assert found is not None
        assert found.to_dict()["visualization"]["kind"] == "none"

    def test_a_signal_question_naming_a_family_is_narrowed_to_it(self) -> None:
        found = pr.answer("What signals are used for liquidity risk?")
        assert found is not None
        said = found.text()
        assert "Liquidity" in said
        assert len(me.catalogue(family="liquidity")) < len(me.catalogue()), (
            "the fixture is wrong: liquidity is the whole catalogue")
        assert str(len(me.catalogue())) not in found.headline, (
            "a question about liquidity was answered with the whole "
            "catalogue")


class TestTheOverviewAnswer:
    @pytest.fixture(scope="class")
    @classmethod
    def said(cls) -> str:
        return pa.get_creditprobe_overview().text()

    @pytest.mark.parametrize("wanted", [
        "Early Warning",
        "IFRS 9",
        "governed",
        "traceable",
    ])
    def test_it_covers_what_the_question_asked(self, said: str,
                                               wanted: str) -> None:
        assert wanted in said, f"the overview never mentions {wanted!r}"

    @pytest.mark.parametrize("held_back", [
        "Data Builder", "Analysis Studio", "Scorecard validation",
        "Published datasets", "Certified analytical methods",
    ])
    def test_it_does_not_answer_the_questions_that_were_not_asked(
            self, said: str, held_back: str) -> None:
        # Progressive disclosure. Every one of these is a real capability with
        # its own answer; none of them is what "What is CreditProbe AI?" asked
        # about, and returning all of them is the defect this replaced.
        assert held_back not in said, (
            f"the introduction explains {held_back!r}, which nobody asked "
            "about yet")

    def test_the_whole_story_is_kept_for_the_question_that_asks_for_it(
            self) -> None:
        told = pa.explain_creditprobe_end_to_end().text()
        assert told.index("The problem") < told.index("What it covers")
        for wanted in ("Borrower 360", "Trace", "Data Builder",
                       "Analysis Studio"):
            assert wanted in told

    def test_the_end_to_end_answer_quotes_this_installation(self) -> None:
        told = pa.explain_creditprobe_end_to_end().text()
        facts = pk.installation()
        assert str(facts["datasets"]) in told
        assert str(facts["signals"]) in told

    def test_it_uses_no_engineering_jargon(self, said: str) -> None:
        for word in ("DuckDB", "Postgres", "PostgreSQL", "Parquet", "FastAPI",
                     "dataclass", "SQL ", "regex", "IR "):
            assert word not in said, (
                f"{word!r} is implementation detail in a product answer")

    def test_it_names_no_model_or_vendor(self, said: str) -> None:
        # §9. A product answer describes what the AI does, never who made it.
        for name in ("Claude", "Anthropic", "GPT", "OpenAI", "Gemini",
                     "Llama", "Qwen"):
            assert name.lower() not in said.lower()

    def test_it_makes_no_unsupported_superlative_claim(self, said: str) -> None:
        for word in ("world-class", "best-in-class", "revolutionary",
                     "unparalleled", "cutting-edge", "state-of-the-art",
                     "seamless", "game-chang"):
            assert word.lower() not in said.lower()


class TestTheAiArchitectureAnswer:
    def test_it_separates_the_three_responsibilities(self) -> None:
        said = pa.describe_ai_role().text()
        # The three headings the remediation asks for, in order.
        for heading in ("## AI does the thinking",
                        "## Agentic AI does the investigating",
                        "## The CreditProbe engine protects the truth"):
            assert heading in said, f"the AI answer has no {heading!r}"
        assert said.index("AI does the thinking") \
            < said.index("Agentic AI does the investigating") \
            < said.index("The CreditProbe engine protects the truth")
        assert "does not compute figures" in said.lower()

    def test_it_ends_on_the_line_that_states_the_bargain(self) -> None:
        said = pa.describe_ai_role().text()
        assert said.rstrip().endswith(f"**{pk.CONTROL_LINE}**")

    def test_the_engine_answer_says_the_ai_may_not_invent_a_figure(self) -> None:
        said = pa.describe_governed_engine().text()
        assert "invent" in said.lower()
        assert "reproducib" in said.lower()

    def test_the_agentic_answer_says_it_is_bounded(self) -> None:
        said = pa.describe_agentic_ai().text()
        assert "bounded" in said.lower()
        assert "governed tools" in said.lower()

    def test_no_layer_answer_names_a_vendor(self) -> None:
        for composed in (pa.describe_ai_role(), pa.describe_agentic_ai(),
                         pa.describe_governed_engine()):
            said = composed.text().lower()
            for name in ("claude", "anthropic", "gpt", "openai", "gemini"):
                assert name not in said


# ==========================================================================
# Reconciliation — the tests that keep the answers true over time
# ==========================================================================


class TestTheRegistryMatchesTheRunningSystem:
    def test_every_capability_names_a_real_feature_area(self) -> None:
        from backend.proof import matrix

        known = {f.area for f in matrix.FEATURES}
        for entry in pk.CAPABILITIES:
            for area in entry.areas:
                assert area in known, (
                    f"{entry.name} claims the feature area {area!r}, which the "
                    "delivered-feature matrix does not have — either the area "
                    "was renamed or the capability no longer exists")

    def test_every_capability_names_a_published_domain(self) -> None:
        from backend.metadata import service as md

        known = {d.name for d in md.domains()}
        for entry in pk.CAPABILITIES:
            for domain in entry.domains:
                assert domain in known, (
                    f"{entry.name} claims to read {domain!r}, which is not a "
                    "published data domain")

    def test_every_capability_evidence_reader_works(self) -> None:
        for entry in pk.CAPABILITIES:
            if entry.evidence is None:
                continue
            facts = entry.facts()
            assert facts, (
                f"{entry.name} declares an evidence reader that returned "
                "nothing, so the answer would quote no live figure")

    def test_the_dataset_count_matches_the_data_builder(self) -> None:
        # §17: "Data Builder dataset counts differ from the assistant's
        # answer" must fail the build.
        from backend.metadata import service as md

        expected = sum(int(getattr(d, "dataset_count", 0) or 0)
                       for d in md.domains())
        assert pk.installation()["datasets"] == expected

    def test_every_named_tool_exists(self) -> None:
        # The remediation names these by name. A tool the routing can choose
        # and the registry cannot serve is a dead end at runtime.
        for wanted in ("get_creditprobe_overview",
                       "list_creditprobe_capabilities",
                       "describe_creditprobe_capability",
                       "describe_creditprobe_architecture",
                       "describe_ai_role", "describe_agentic_ai",
                       "describe_governed_engine",
                       "describe_early_warning_methodology",
                       "describe_tac_methodology",
                       "describe_ifrs9_intelligence",
                       "describe_rating_intelligence",
                       "describe_borrower360", "describe_data_builder",
                       "describe_analysis_studio", "describe_stress_testing",
                       "describe_scorecard_validation",
                       "describe_trace_lineage",
                       "describe_external_intelligence",
                       "describe_workflow",
                       "describe_governance_controls"):
            assert wanted in pa.TOOLS, f"{wanted} is not registered"

    def test_every_tool_returns_an_answer(self) -> None:
        for name in pa.tool_names():
            found = pa.call(name)
            assert found is not None, f"{name} returned nothing"
            assert found.text().strip(), f"{name} returned an empty answer"

    def test_every_routing_target_is_a_registered_tool(self) -> None:
        for question in PRODUCT_QUESTIONS:
            intent = pr.read(question)
            assert intent.tool in pa.TOOLS, (
                f"{question!r} routes to {intent.tool!r}, which does not exist")


class TestTheMethodologyMatchesTheEngine:
    def test_every_signal_family_belongs_to_a_layer(self) -> None:
        # §17: "the signal catalogue differs from the Early Warning engine"
        # must fail the build. A family the engine evaluates and the
        # methodology does not mention is a signal firing into an explanation
        # that denies it exists.
        assert me.unmapped_families() == (), (
            f"{list(me.unmapped_families())} are evaluated by the engine and "
            "belong to no layer of the methodology")

    def test_the_catalogue_holds_every_governed_signal(self) -> None:
        from backend.early_warning import taxonomy as tx

        assert len(me.catalogue()) == len(tx.SIGNALS)

    def test_the_layers_partition_the_families(self) -> None:
        from backend.early_warning import taxonomy as tx

        claimed: list[str] = []
        for layer in me.layers():
            claimed.extend(layer.families)
        assert len(claimed) == len(set(claimed)), (
            "a signal family is claimed by two layers, so its signals would "
            "be described twice")
        assert set(claimed) == set(tx.FAMILIES)

    def test_frequency_is_read_from_the_data(self) -> None:
        # §14: "Do not claim daily frequency if the available data is
        # quarterly." Every signal reads the borrower snapshot, which
        # publishes quarterly, so quarterly is the only honest answer.
        for dataset, frequency in me.frequencies().items():
            assert frequency in (me.QUARTERLY, me.ANNUAL, me.MONTHLY,
                                 me.UNKNOWN_FREQUENCY), \
                f"{dataset} claims {frequency}, which the data does not support"

    def test_no_signal_claims_a_frequency_its_source_does_not_publish(
            self) -> None:
        published = me.frequencies()
        for entry in me.catalogue():
            assert entry.frequency == published[entry.dataset]

    def test_every_signal_declares_what_the_catalogue_promises(self) -> None:
        # §14's required columns, each on every entry.
        for entry in me.catalogue():
            assert entry.family and entry.family_label
            assert entry.layer and entry.layer_name
            assert entry.label and entry.means
            assert entry.dataset and entry.fields
            assert entry.grain and entry.frequency
            assert entry.test and entry.direction
            assert entry.severity and entry.owner and entry.version

    def test_the_external_layer_is_configured_and_still_states_its_limit(
            self) -> None:
        # This layer used to be empty and said so. It is configured now, and
        # the honesty requirement did not go away with the gap: the layer
        # reads external and network FIELDS on the borrower snapshot, and it
        # still does not read the macro SERIES, so it has to keep saying which
        # of the two it does.
        external = next(entry for entry in me.layers()
                        if entry.key == me.LAYER_EXTERNAL)
        assert external.families, "layer 4 has no families"
        configured = me.catalogue(layer_key=me.LAYER_EXTERNAL)
        assert configured, "layer 4 claims families but carries no signals"
        assert external.gap, (
            "the external layer reads borrower-level external fields and not "
            "the macro series, and an answer that does not say so reads as a "
            "framework that watches the macro picture when it does not")

    def test_every_layer_four_signal_reads_a_real_field(self) -> None:
        # Small and credible beats artificial volume: every signal here has to
        # bind to a field the catalogue actually publishes, or it is decoration
        # that makes the layer look full.
        for entry in me.catalogue(layer_key=me.LAYER_EXTERNAL):
            assert entry.dataset and entry.fields, (
                f"{entry.key} is in layer 4 without a dataset and field")


class TestTac:
    """§11E. TAC was undefined. It has since been defined, and the answer now
    reads the definition out of the engine rather than restating it.

    The earlier version of this class asserted the opposite — that TAC was not
    defined and that no expansion of the acronym might appear anywhere. That
    was correct while it was true. The definition was supplied (Threshold,
    Action, Classifier) and implemented, so the tests that guarded the absence
    now guard the implementation: that the letters come from the taxonomy, that
    the C is five configured patterns rather than an aspiration, and that no
    signal is left without a mechanism.
    """

    def test_it_is_reported_as_defined(self) -> None:
        assert me.tac().status == me.TAC_STATUS_DEFINED
        assert me.tac().to_dict()["defined"] is True

    def test_the_three_letters_are_read_from_the_engine(self) -> None:
        import backend.early_warning.taxonomy as tx

        types = me.tac().types
        assert [t["letter"] for t in types] == ["T", "A", "C"]
        counted = {t["type"]: t["signals"] for t in types}
        assert counted[tx.THRESHOLD_BASED] == sum(
            1 for s in tx.SIGNALS if s.tac == tx.THRESHOLD_BASED)
        assert counted[tx.ACTION_BASED] == sum(
            1 for s in tx.SIGNALS if s.tac == tx.ACTION_BASED)

    def test_every_signal_carries_exactly_one_mechanism(self) -> None:
        import backend.early_warning.taxonomy as tx

        for signal in tx.SIGNALS:
            assert signal.tac in tx.TAC_TYPES, (
                f"{signal.key} has no detection mechanism")

    def test_the_classifier_letter_is_configured_not_claimed(self) -> None:
        # "Do not claim a classifier exists if it is not configured."
        from backend.early_warning import classifiers as cls

        entry = next(t for t in me.tac().types if t["letter"] == "C")
        assert entry["classifiers"] == len(cls.CLASSIFIERS) >= 1
        for configured in entry["configured"]:
            assert configured["components"], (
                f"{configured['key']} names no component signals")
            assert 1 <= configured["needs"] <= configured["of"]
        assert cls.unknown_components() == (), (
            "a classifier names a component no governed signal provides")

    def test_a_classifier_does_not_double_count_as_signals(self) -> None:
        # A classifier is a pattern OVER signals. Counting it in the signal
        # column would count the same evidence twice and inflate the
        # catalogue, which is the arithmetic this module exists to prevent.
        import backend.early_warning.taxonomy as tx

        types = me.tac().types
        assert sum(t["signals"] for t in types) == len(tx.SIGNALS)

    def test_the_answer_says_what_each_letter_means(self) -> None:
        said = pa.describe_tac_methodology().text()
        for letter in ("Threshold", "Action", "Classifier"):
            assert letter.lower() in said.lower(), (
                f"the TAC answer never says what {letter[0]} stands for")

    def test_the_answer_separates_mechanism_from_layer(self) -> None:
        # The one confusion this answer has to prevent: TAC is how a signal is
        # DETECTED, the layers are what it is ABOUT, and a reader who conflates
        # them will think there are seven categories.
        said = pa.describe_tac_methodology().text().lower()
        assert "layer" in said

    def test_the_deep_answer_names_every_configured_classifier(self) -> None:
        from backend.early_warning import classifiers as cls

        said = pa.describe_tac_methodology(detail=True).text()
        for entry in cls.CLASSIFIERS:
            assert entry.label in said, (
                f"the classifier {entry.key} is configured and unnamed")

    def test_the_answer_records_that_the_definition_was_supplied(self) -> None:
        # The provenance matters: it says the definition arrived rather than
        # being inferred, which is what stops the next reader assuming somebody
        # guessed it.
        assert me.tac().source
        assert me.TAC_SEARCHED, (
            "the record of what was searched while TAC was undefined was "
            "dropped, so the answer can no longer say what it looked like "
            "before the definition arrived")


class TestTheMethodologyAnswer:
    @pytest.fixture(scope="class")
    @classmethod
    def said(cls) -> str:
        return pa.describe_early_warning_methodology().text()

    @pytest.mark.parametrize("heading", [
        "## What it is for", "## Four layers",
        "## How a signal becomes something you act on",
        "## What a warning is telling you", "## Severity and ownership",
    ])
    def test_it_has_the_section_the_structure_requires(self, said: str,
                                                       heading: str) -> None:
        assert heading in said, f"the methodology answer has no {heading!r}"

    def test_every_layer_appears_with_its_signals(self, said: str) -> None:
        for layer in me.layers():
            assert f"layer {layer.number}" in said.lower()

    def test_it_quotes_the_real_signal_count(self, said: str) -> None:
        from backend.early_warning import taxonomy as tx

        assert str(len(tx.SIGNALS)) in said

    def test_it_offers_the_catalogue_rather_than_dumping_it(self,
                                                            said: str) -> None:
        composed = pa.describe_early_warning_methodology()
        assert "expand the signal catalogue" in said.lower(), (
            "the high-level answer does not offer the detail it held back")
        assert any("catalogue" in f.lower() for f in composed.follow_ups)
        for label in (e.label for e in me.catalogue()):
            assert label not in said, (
                f"the high-level answer lists the signal {label!r}, which is "
                "the detail it was supposed to offer rather than dump")

    def test_asking_for_detail_expands_it(self) -> None:
        brief = pa.describe_early_warning_methodology()
        full = pa.describe_early_warning_methodology(detail=True)
        assert len(full.text()) > 2 * len(brief.text())
        assert "Quarterly" in full.text()
        assert "## Trace and governance" in full.text()
        assert "## AI investigation" in full.text()
        for layer in me.layers():
            for entry in me.catalogue(layer_key=layer.key):
                assert entry.label in full.text()

    def test_the_ask_path_expands_it_when_the_question_asks(self) -> None:
        brief = pr.answer("What is the Early Warning methodology?")
        full = pr.answer("Explain the Early Warning methodology in detail.")
        assert brief is not None and full is not None
        assert len(full.text()) > 2 * len(brief.text())


class TestWarningLanguage:
    """§15. Engine words describe a rule; a credit officer wants the borrower."""

    def test_the_states_are_credit_language(self) -> None:
        states = {state for state, _ in me.WARNING_STATES}
        assert states == {"New warning", "Persistent warning",
                          "Worsening warning", "Improving", "Resolved"}

    def test_no_state_leads_with_engine_wording(self) -> None:
        for state, _ in me.WARNING_STATES:
            for engine_word in ("firing", "fired", "rule", "condition met"):
                assert engine_word not in state.lower()

    def test_persistent_is_defined_against_observation_periods(self) -> None:
        means = dict(me.WARNING_STATES)["Persistent warning"]
        assert "observation period" in means
        assert "current" in means and "previous" in means

    def test_every_state_names_its_observation_periods(self) -> None:
        for _, means in me.WARNING_STATES:
            assert "observation period" in means, (
                "a warning state that does not say which periods it compares "
                "cannot be checked by the person reading it")


class TestTheAskPathAnswersProductQuestions:
    """Through the real route, not through the module."""

    @pytest.mark.parametrize("question", [
        "What is CreditProbe AI?",
        "What is the CreditProbe Early Warning methodology?",
        "What is TAC methodology?",
        "How does CreditProbe use AI?",
    ])
    def test_it_answers_rather_than_refusing(self, question: str) -> None:
        from backend.orchestration.executor import answer_investigation

        try:
            investigation, answered = answer_investigation(question,
                                                           persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the Ask path is not available: {exc}")
        said = str(investigation.narrative.direct_answer or "")
        assert said.strip()
        assert "no governed data about CreditProbe" not in said
        assert answered.result is not None
        assert answered.result.execution == "product_knowledge"

    def test_it_proposes_no_chart(self) -> None:
        from backend.orchestration.executor import answer_investigation

        try:
            _, answered = answer_investigation("What is CreditProbe AI?",
                                               persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the Ask path is not available: {exc}")
        assert not answered.result.chart

    def test_a_portfolio_question_still_reaches_the_engine(self) -> None:
        # The guard on the guard: adding a product route must not capture a
        # question about the book.
        from backend.orchestration.executor import answer_investigation

        try:
            _, answered = answer_investigation(
                "Which customers were downgraded and had expected credit "
                "loss rise in Q1 2026?", persist=False)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the Ask path is not available: {exc}")
        assert answered.result is None \
            or answered.result.execution != "product_knowledge"
        assert getattr(answered, "runtime", None) is not None


class TestTheProductLayerReadsNoBorrowerData:
    """It describes the product. It must never become a data path."""

    def test_no_answer_carries_rows(self) -> None:
        for name in pa.tool_names():
            found = pa.call(name)
            assert found is not None
            payload: dict[str, Any] = found.to_dict()
            assert "rows" not in payload

    def test_the_registry_holds_no_borrower_identifier(self) -> None:
        import re

        text = " ".join(
            [pk.PURPOSE, pk.PROBLEM, pk.WHY_THE_SPLIT]
            + [c.does + c.matters + c.used_by for c in pk.CAPABILITIES])
        assert not re.search(r"\b(?:SA|CORP)-\d+\b", text), (
            "the product registry names a borrower, which would make a "
            "product answer depend on the book")
