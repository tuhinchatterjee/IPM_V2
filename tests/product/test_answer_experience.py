"""
The answer EXPERIENCE, as opposed to the answer's facts.

`test_product_knowledge.py` holds the previous remediation: that CreditProbe
can explain itself, that what it says reconciles to the running installation,
and that it does not invent TAC. Every one of those still passes and none of
them was weakened here.

This file holds the defect that came after: the answers were true and nobody
could read them. "What is CreditProbe AI?" returned five thousand characters
of accurate product documentation in one run of prose with upper-cased
headings, and the answer surface rendered it inside a single paragraph.

So these tests are about SELECTION, SHAPE and SIZE:

*   an introduction is an introduction, not the manual (progressive disclosure)
*   each question gets the content that answers IT, not the union of everything
*   every answer carries real structure - headings, bullets, blank lines
*   nothing is a wall of prose, and nothing runs past its length band
*   the eleven-point composition gate passes on every question a user can ask
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.product import answers as pa
from backend.product import compose as co
from backend.product import knowledge as pk
from backend.product import methodology as me
from backend.product import routing as pr

#: Section 16. The exact acceptance questions, in the order they are given.
ACCEPTANCE: tuple[str, ...] = (
    "What is CreditProbe AI?",
    "What can CreditProbe do?",
    "What features does CreditProbe have?",
    "Why should a credit risk officer use CreditProbe?",
    "How can CreditProbe help a corporate credit risk team?",
    "Why is CreditProbe different from a normal BI dashboard?",
    "What is the role of AI in CreditProbe?",
    "What is Agentic AI doing inside CreditProbe?",
    "What is Borrower 360?",
    "What is the Early Warning methodology?",
    "Explain the Early Warning methodology in detail.",
    "What is Trace and why does it matter?",
    "Explain CreditProbe end to end.",
)

#: Every other product question the routing can reach, so the guarantees below
#: hold for the whole surface rather than for thirteen rehearsed cases.
OTHERS: tuple[str, ...] = (
    "What is TAC?",
    "What signals are used for liquidity risk?",
    "How does an Early Warning signal become a Risk Case?",
    "What does a persistent warning mean?",
    "Explain the CreditProbe architecture.",
    "What does the governed CreditProbe engine do?",
    "What is IFRS 9 intelligence?",
    "What is stress testing?",
    "What is Data Builder?",
    "What is connected counterparty and group risk?",
)

EVERY_QUESTION = ACCEPTANCE + OTHERS


def answer_to(question: str) -> pa.Answer:
    found = pr.answer(question)
    assert found is not None, f"{question!r} produced no product answer"
    return found


# ==========================================================================
# The composition gate — section 14
# ==========================================================================


class TestTheCompositionGate:
    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_every_question_passes_all_eleven_checks(self,
                                                     question: str) -> None:
        composed = answer_to(question)
        review = co.inspect(composed)
        assert review.ok, "\n".join(
            f"{c.name}: {c.question} — {c.detail}" for c in review.failures)

    def test_the_gate_runs_eleven_checks(self) -> None:
        review = co.inspect(pa.get_creditprobe_overview())
        assert len(review.checks) == 11
        assert len({c.name for c in review.checks}) == 11

    def test_the_gate_can_actually_fail(self) -> None:
        # A gate nothing can fail is decoration. This is the answer the
        # remediation describes: one unbroken block, no structure, no opening.
        dumped = co.Answer(
            topic="dump", band=co.SHORT,
            headline=" ".join(["Everything CreditProbe knows about itself, "
                               "at once, in one paragraph."] * 12),
            sections=[co.Section(key="more", title="",
                                 body=[" ".join(["and more of it."] * 200)])])
        review = co.inspect(dumped)
        assert not review.ok
        failed = {c.name for c in review.failures}
        assert {"concise_opening", "short_paragraphs"} <= failed

    def test_it_rejects_marketing_language(self) -> None:
        composed = co.Answer(
            topic="x", band=co.SHORT, headline="A world-class platform.",
            sections=[co.Section(key="a", title="What it does",
                                 body=["Seamless, best-in-class analytics."])],
            follow_ups=["What is CreditProbe AI?"])
        assert "tone" in {c.name for c in co.inspect(composed).failures}

    def test_it_rejects_implementation_vocabulary(self) -> None:
        composed = co.Answer(
            topic="x", band=co.SHORT, headline="It answers questions.",
            sections=[co.Section(key="a", title="What it does",
                                 body=["The backend returns a JSON payload."])],
            follow_ups=["What is CreditProbe AI?"])
        assert "no_internals" in {c.name for c in co.inspect(composed).failures}

    def test_it_rejects_the_microcopy_the_remediation_replaced(self) -> None:
        composed = co.Answer(
            topic="x", band=co.SHORT, headline="It answers questions.",
            sections=[co.Section(key="a", title="Business rationale",
                                 body=["The following capabilities are "
                                       "available."])],
            follow_ups=["What is CreditProbe AI?"])
        assert "tone" in {c.name for c in co.inspect(composed).failures}


# ==========================================================================
# Length — section 6
# ==========================================================================


class TestLength:
    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_no_answer_runs_past_its_band(self, question: str) -> None:
        composed = answer_to(question)
        _floor, ceiling = co.BANDS[composed.band]
        words = co.word_count(composed.markdown())
        assert words <= ceiling, (
            f"{question!r} returned {words} words against a "
            f"{composed.band} ceiling of {ceiling}")

    def test_the_introduction_is_an_introduction(self) -> None:
        # The defect, stated as a number: 5,079 characters for "What is
        # CreditProbe AI?". A reader gets a page, not a manual.
        said = answer_to("What is CreditProbe AI?").markdown()
        assert len(said) < 3000, f"the introduction is {len(said)} characters"
        assert co.BANDS[co.MEDIUM][0] <= co.word_count(said) \
            <= co.BANDS[co.MEDIUM][1]

    def test_a_single_capability_answers_short(self) -> None:
        composed = answer_to("What is Borrower 360?")
        assert composed.band == co.SHORT
        assert co.word_count(composed.markdown()) <= co.BANDS[co.SHORT][1]

    def test_only_the_end_to_end_question_gets_the_long_form(self) -> None:
        detailed = [q for q in ACCEPTANCE
                    if answer_to(q).band == co.DETAILED]
        assert detailed == ["Explain the Early Warning methodology in detail.",
                            "Explain CreditProbe end to end."]

    def test_the_long_form_is_longer_than_the_introduction(self) -> None:
        assert co.word_count(answer_to("Explain CreditProbe end to end.")
                             .markdown()) \
            > co.word_count(answer_to("What is CreditProbe AI?").markdown())


# ==========================================================================
# Structure and whitespace — section 5
# ==========================================================================


class TestStructure:
    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_every_answer_has_headings(self, question: str) -> None:
        said = answer_to(question).markdown()
        assert co.headings_of(said), f"{question!r} has no headings at all"

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_every_answer_is_more_than_one_block(self, question: str) -> None:
        assert len(co.blocks_of(answer_to(question).markdown())) >= 4

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_no_answer_is_a_wall_of_prose(self, question: str) -> None:
        for paragraph in co.paragraphs_of(answer_to(question).markdown()):
            assert len(paragraph.split()) <= co.MAX_PARAGRAPH_WORDS, (
                f"{question!r} has a {len(paragraph.split())}-word paragraph")

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_every_block_is_separated_by_a_blank_line(self,
                                                      question: str) -> None:
        said = answer_to(question).markdown()
        assert "\n\n" in said
        assert "\n\n\n" not in said, "empty blocks make ragged whitespace"

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_no_heading_shouts(self, question: str) -> None:
        # The old composer upper-cased every section title, which is what
        # made the answer read as a document dump rather than as writing.
        for _level, heading in co.headings_of(answer_to(question).markdown()):
            assert heading != heading.upper() or not heading.isalpha()

    def test_the_feature_answer_uses_the_glance_structure(self) -> None:
        said = answer_to("What features does CreditProbe have?").markdown()
        assert "## CreditProbe at a glance" in said
        levels = [level for level, _ in co.headings_of(said)]
        assert levels.count(3) >= 10, (
            "capabilities are supposed to be subheadings under the glance")

    def test_a_process_flow_is_text_rather_than_a_chart(self) -> None:
        said = answer_to("What is CreditProbe AI?").markdown()
        assert co.FLOW_ARROW.strip() in said
        assert "> " in said

    def test_not_every_answer_carries_a_flow(self) -> None:
        # Section 12: "Do not make every answer contain a flowchart."
        with_flow = [q for q in EVERY_QUESTION
                     if co.FLOW_ARROW.strip() in answer_to(q).markdown()]
        assert 0 < len(with_flow) < len(EVERY_QUESTION), (
            "a flow on every answer is decoration, and a flow on none loses "
            "the one thing a text infographic is good at")
        # A single-capability answer is a paragraph of explanation. It has no
        # process to draw.
        assert co.FLOW_ARROW.strip() not in answer_to(
            "What is Borrower 360?").markdown()


# ==========================================================================
# Progressive disclosure — sections 1 and 10
# ==========================================================================


class TestProgressiveDisclosure:
    def test_the_introduction_holds_back_the_capability_catalogue(self) -> None:
        said = answer_to("What is CreditProbe AI?").markdown()
        named = [c.name for c in pk.capabilities() if c.name in said]
        assert len(named) <= 2, (
            f"the introduction explains {named}, which is the capability "
            "question's job")

    def test_the_introduction_names_no_early_warning_signal(self) -> None:
        said = answer_to("What is CreditProbe AI?").markdown()
        for entry in me.catalogue():
            assert entry.label not in said

    def test_the_methodology_offers_the_catalogue_rather_than_dumping_it(
            self) -> None:
        brief = answer_to("What is the Early Warning methodology?")
        assert brief.held_back(), "nothing was held back to offer"
        assert not brief.deep
        assert "expand the signal catalogue" in brief.markdown().lower()

    def test_asking_for_detail_returns_what_was_held_back(self) -> None:
        brief = answer_to("What is the Early Warning methodology?")
        full = answer_to("Explain the Early Warning methodology in detail.")
        assert full.deep and not brief.deep
        assert not full.held_back()
        held = {s.key for s in brief.held_back()}
        shown = {s.key for s in full.shown()}
        assert held <= shown

    def test_the_capability_answer_holds_back_the_installation_counts(
            self) -> None:
        composed = answer_to("What is Borrower 360?")
        assert any(s.key == "installation" for s in composed.sections)
        assert not any(s.key == "installation" for s in composed.shown())

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_anything_held_back_is_offered(self, question: str) -> None:
        composed = answer_to(question)
        if composed.held_back():
            assert composed.follow_ups, (
                "content was held back and never offered, which is not "
                "disclosure, it is omission")


# ==========================================================================
# Intent-specific selection — section 1
# ==========================================================================


class TestSelection:
    def test_a_capability_question_is_about_that_capability(self) -> None:
        said = answer_to("What is Borrower 360?").markdown()
        assert "Borrower 360" in said
        others = [c.name for c in pk.capabilities()
                  if c.key != "borrower360" and c.name in said]
        assert len(others) <= 1, f"a Borrower 360 answer explains {others}"

    def test_an_ai_question_is_about_the_ai(self) -> None:
        said = answer_to("What is the role of AI in CreditProbe?").markdown()
        assert "AI does the thinking" in said
        # It may MENTION Early Warning - investigating a case is one of the
        # things the agentic layer does - but it must not explain it.
        assert "Four layers" not in said
        for entry in me.catalogue():
            assert entry.label not in said

    def test_an_agentic_question_is_about_the_agentic_layer_only(self) -> None:
        said = answer_to(
            "What is Agentic AI doing inside CreditProbe?").markdown()
        assert "AI does the thinking" not in said
        assert "bounded" in said.lower()

    def test_the_three_business_questions_get_three_different_answers(
            self) -> None:
        topics = {answer_to(q).topic for q in (
            "Why should a credit risk officer use CreditProbe?",
            "How can CreditProbe help a corporate credit risk team?",
            "Why is CreditProbe different from a normal BI dashboard?")}
        assert topics == {"value", "team_workflow", "versus_dashboard"}

    def test_no_two_acceptance_answers_are_the_same_text(self) -> None:
        # Section 17: the structure should fit the question, not a template.
        said = [answer_to(q).markdown() for q in ACCEPTANCE]
        assert len(set(said)) == len(said) - 1, (
            "only the two feature phrasings should share an answer")

    def test_the_answers_do_not_share_one_template(self) -> None:
        shapes = {tuple(h for _, h in co.headings_of(answer_to(q).markdown()))
                  for q in ACCEPTANCE}
        assert len(shapes) >= 8


# ==========================================================================
# Voice — sections 2, 3, 13 and 18
# ==========================================================================


class TestVoice:
    def test_the_introduction_speaks_in_the_first_person(self) -> None:
        said = answer_to("What is CreditProbe AI?").markdown()
        assert said.startswith("I'm CreditProbe AI")
        assert "AI Risk Officer" in said

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_first_person_is_not_overused(self, question: str) -> None:
        said = answer_to(question).markdown()
        sentences = max(1, said.count(".") + said.count("?"))
        opens = sum(1 for line in said.split("\n") if line.startswith("I "))
        assert opens / sentences < 0.25, (
            f"{question!r} opens {opens} lines with 'I'")

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_no_answer_names_a_model_or_a_vendor(self, question: str) -> None:
        said = answer_to(question).markdown().lower()
        for name in ("claude", "anthropic", "gpt", "openai", "gemini",
                     "llama", "qwen", "mistral"):
            assert name not in said

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_no_answer_overclaims(self, question: str) -> None:
        said = answer_to(question).markdown().lower()
        # "Guarantee" is not on this list: a guarantee is a credit-risk
        # instrument, and a deterministic engine really does guarantee that
        # the same question on the same data returns the same figures. What
        # is banned is the claim no product can support.
        for word in ("guarantees accuracy", "eliminates risk", "never wrong",
                     "always right", "fully automated", "without a human",
                     "100% ", "perfectly", "removes the need for judgement"):
            assert word not in said, f"{question!r} claims {word!r}"

    def test_scenario_language_is_hedged(self) -> None:
        # Section 18: stress scenarios are configured one at a time, so an
        # answer implying they all already exist is an overclaim.
        for question in ("What is CreditProbe AI?",
                         "Why should a credit risk officer use CreditProbe?"):
            said = answer_to(question).markdown().lower()
            if "what if" in said or "scenario" in said:
                assert "configured" in said


# ==========================================================================
# Nudges — section 11
# ==========================================================================


class TestFollowUps:
    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_between_one_and_three(self, question: str) -> None:
        composed = answer_to(question)
        assert 1 <= len(composed.follow_ups) <= 3

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_none_repeats_the_question_it_follows(self,
                                                  question: str) -> None:
        composed = answer_to(question)
        asked = question.strip().rstrip("?.").lower()
        for nudge in composed.follow_ups:
            assert nudge.strip().rstrip("?.").lower() != asked

    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_every_nudge_is_answerable(self, question: str) -> None:
        # A suggestion the product cannot answer is worse than no suggestion.
        for nudge in answer_to(question).follow_ups:
            intent = pr.read(nudge)
            assert intent.is_product, (
                f"{nudge!r}, offered after {question!r}, does not route to a "
                "product answer")
            assert intent.tool in pa.TOOLS

    def test_the_nudges_are_not_one_canned_list(self) -> None:
        offered = [tuple(answer_to(q).follow_ups) for q in ACCEPTANCE]
        assert len(set(offered)) >= 9


# ==========================================================================
# No charts — section 12
# ==========================================================================


class TestNoQuantitativeChart:
    @pytest.mark.parametrize("question", EVERY_QUESTION)
    def test_no_product_answer_proposes_one(self, question: str) -> None:
        payload: dict[str, Any] = answer_to(question).to_dict()
        assert payload["visualization"]["kind"] == "none"


# ==========================================================================
# The composed payload — what the answer surface receives
# ==========================================================================


class TestThePayload:
    def test_the_answer_string_carries_the_structure(self) -> None:
        # The other half of the defect: the sections travelled in a side
        # channel and the surface rendered a flattened string. The Markdown
        # has to be IN the answer.
        payload = answer_to("What is CreditProbe AI?").to_dict()
        assert payload["answer"] == payload["markdown"]
        assert "## " in payload["answer"]
        assert "\n\n" in payload["answer"]

    def test_the_payload_reports_its_own_composition(self) -> None:
        payload = answer_to("What is CreditProbe AI?").to_dict()
        assert payload["composition"]["ok"] is True
        assert payload["composition"]["failed"] == []
        assert payload["band"] == co.MEDIUM
        assert payload["word_count"] > 0

    def test_the_payload_names_what_it_held_back(self) -> None:
        payload = answer_to("What is the Early Warning methodology?").to_dict()
        assert payload["held_back"]
        assert not any(s["key"] in payload["held_back"]
                       for s in payload["sections"])

    def test_no_answer_carries_rows(self) -> None:
        for question in EVERY_QUESTION:
            assert "rows" not in answer_to(question).to_dict()


# ==========================================================================
# Reconciliation — section 18
# ==========================================================================


class TestItReconcilesToTheInstallation:
    def test_the_opening_names_only_configured_capabilities(self) -> None:
        for key in pk.CONNECTED_PICTURE:
            assert pk.capability(key) is not None, (
                f"the introduction connects {key!r}, which is not a "
                "configured capability")

    def test_every_short_name_is_a_configured_capability(self) -> None:
        for key in pk.SHORT_NAMES:
            assert pk.capability(key) is not None

    def test_the_glance_lists_every_configured_capability(self) -> None:
        said = answer_to("What features does CreditProbe have?").markdown()
        for entry in pk.capabilities():
            assert entry.name in said, (
                f"{entry.name} is configured and the feature answer omits it")

    def test_the_signal_count_is_the_engine_count(self) -> None:
        from backend.early_warning import taxonomy as tx

        said = answer_to("What is the Early Warning methodology?").markdown()
        assert str(len(tx.SIGNALS)) in said

    def test_every_tool_still_composes_cleanly(self) -> None:
        for name in pa.tool_names():
            found = pa.call(name)
            assert found is not None, f"{name} returned nothing"
            review = co.inspect(found)
            assert review.ok, f"{name}: {[c.name for c in review.failures]}"
