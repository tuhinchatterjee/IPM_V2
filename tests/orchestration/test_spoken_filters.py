"""A governed filter, said out loud, on every surface that says it.

The defect this locks down
--------------------------
"Show Stage 2 borrowers." answered correctly — 1,167 customers — and then
described its own population as the digit ``2``:

    Together these 10 hold 11.50% of 2 exposure at default.
    Shares are of 2 exposure, not of the whole book.
    Each row's share of 2, not of the whole book.
    2 · Q2 2026 · exposure at default, expected credit loss, IFRS 9 stage

Four surfaces, four separate ``", ".join(value for _, value in filters)``
expressions, and a reader who cannot tell what population the percentages are
of. The first sentence was right the whole time, because it went through a
reader that knew a coded value needs its field's name. The rest did not.

So the rule is one function now, on the scope frame, and these tests hold every
caller to it rather than to the four strings that happened to be wrong.
"""

from __future__ import annotations

import backend.orchestration.assembly as asm
import backend.orchestration.scope as sc


class _Widened:
    """The shape `AnalysisBuild.widened` carries: field, value, op."""

    def __init__(self, field: str, value: str, op: str) -> None:
        self.field, self.value, self.op = field, value, op


class TestACodedValueIsNamedByItsField:

    def test_a_stage_is_said_as_a_stage(self):
        assert sc.say("ifrs9_stage", "2") == "Stage 2"

    def test_a_grade_is_said_as_a_grade(self):
        assert sc.say("internal_grade", "7") == "grade 7"

    def test_a_dpd_bucket_keeps_its_name(self):
        assert sc.say("dpd_bucket", "90") == "DPD bucket 90"

    def test_an_unmapped_numeric_field_still_gets_a_name(self):
        # The map is a curation of good English, not the safety net. A field
        # nobody has phrased yet must not fall through to a bare digit.
        assert sc.say("charge_rank", "1") == "charge rank 1"
        assert sc.say("some_new_code", "4") == "some new code 4"

    def test_a_negative_or_decimal_code_is_still_a_code(self):
        assert sc.say("some_new_code", "-1") == "some new code -1"
        assert sc.say("some_new_code", "2.5") == "some new code 2.5"


class TestAValueThatIsAlreadyAName:

    def test_a_sector_is_left_alone(self):
        assert sc.say("sector", "Shipping") == "Shipping"

    def test_a_country_is_left_alone(self):
        assert sc.say("country", "Saudi Arabia") == "Saudi Arabia"

    def test_a_rating_letter_is_left_alone(self):
        # "BB" is not a digit and reads as itself. "internal_rating BB" is
        # worse English than "BB".
        assert sc.say("internal_rating", "BB") == "BB"


class TestAWidenedRestrictionSaysSo:

    def test_stage_two_or_worse(self):
        assert sc.say("ifrs9_stage", "2", "gte") == "Stage 2 or worse"

    def test_stage_two_or_better(self):
        assert sc.say("ifrs9_stage", "2", "lte") == "Stage 2 or better"

    def test_an_exact_restriction_gains_nothing(self):
        assert sc.say("ifrs9_stage", "2", "") == "Stage 2"
        assert sc.say("ifrs9_stage", "2", "eq") == "Stage 2"

    def test_the_qualifier_follows_the_right_filter(self):
        # Two restrictions, one widened. The "or worse" must not land on the
        # sector — that would describe a population nobody asked for.
        said = sc.phrase([("ifrs9_stage", "2"), ("sector", "Shipping")],
                         [_Widened("ifrs9_stage", "2", "gte")])
        assert said == "Stage 2 or worse, Shipping"


class TestBothWaysOfWritingAFilterDown:

    def test_pairs(self):
        assert sc.phrase([("ifrs9_stage", "2")]) == "Stage 2"

    def test_the_mapping_the_frame_stores(self):
        assert sc.phrase([{"field": "ifrs9_stage", "value": "2"}]) == "Stage 2"

    def test_the_two_forms_agree(self):
        pairs = [("ifrs9_stage", "2"), ("sector", "Shipping")]
        mapped = [{"field": f, "value": v} for f, v in pairs]
        assert sc.phrase(pairs) == sc.phrase(mapped) == "Stage 2, Shipping"

    def test_no_filters_is_an_empty_phrase_not_a_crash(self):
        assert sc.phrase([]) == ""
        assert sc.phrase(None) == ""


class TestTheLineAboveTheTable:
    """`ScopeFrame.line()` — the strip a reader sees before the number."""

    def test_a_stage_scope_names_the_stage(self):
        frame = sc.ScopeFrame(
            filters=[{"field": "ifrs9_stage", "value": "2"}],
            period="Q2 2026", metrics=["exposure at default"])
        assert frame.line() == "Stage 2 · Q2 2026 · exposure at default"

    def test_the_line_never_opens_with_a_bare_digit(self):
        # The exact regression: "2 · Q2 2026 · …".
        frame = sc.ScopeFrame(filters=[{"field": "ifrs9_stage", "value": "2"}],
                              period="Q2 2026")
        assert not frame.line().startswith("2 ")

    def test_a_named_scope_is_unchanged(self):
        frame = sc.ScopeFrame(filters=[{"field": "sector", "value": "Shipping"}],
                              period="Q2 2026")
        assert frame.line() == "Shipping · Q2 2026"

    def test_an_unfiltered_line_still_says_the_whole_portfolio(self):
        assert sc.ScopeFrame(period="Q2 2026").line() == \
            "the whole portfolio · Q2 2026"

    def test_a_carried_population_still_wins(self):
        # A pinned set of identities is a stronger statement about what the
        # figures cover than the filters that produced it.
        frame = sc.ScopeFrame(entity_ids=["a", "b"], entity_key="customer_id",
                              filters=[{"field": "ifrs9_stage", "value": "2"}],
                              period="Q2 2026")
        assert frame.line().startswith("2 customers carried from the previous")


class TestAssemblyReadsTheSameRule:
    """The answer's prose and the line above it must not disagree."""

    def test_the_assembly_reader_delegates(self):
        assert asm._scope_phrase([("ifrs9_stage", "2")]) == "Stage 2"

    def test_it_agrees_with_the_frame(self):
        pairs = [("ifrs9_stage", "3"), ("sector", "Shipping")]
        frame = sc.ScopeFrame(
            filters=[{"field": f, "value": v} for f, v in pairs])
        assert asm._scope_phrase(pairs) == sc.phrase(pairs)
        assert frame.line().startswith(asm._scope_phrase(pairs))

    def test_the_widened_qualifier_survives_the_delegation(self):
        said = asm._scope_phrase([("ifrs9_stage", "2")],
                                 [_Widened("ifrs9_stage", "2", "gte")])
        assert said == "Stage 2 or worse"

    def test_no_caller_joins_raw_filter_values_any_more(self):
        # A mechanism test, not a string test: the four expressions that
        # produced "of 2" were all the same shape. If one comes back, this
        # fails before a browser does.
        import pathlib
        source = pathlib.Path(asm.__file__).read_text(encoding="utf-8")
        for banned in ('", ".join(v for _, v in build.filters)',
                       '", ".join(str(value) for _, value in (build.filters'):
            assert banned not in source, (
                f"a caller is joining raw filter values again: {banned}")


class _Build:
    """The three attributes `frame_of` reads for its filters."""

    def __init__(self, filters, widened=()):
        self.filters = list(filters)
        self.widened = list(widened)
        self.plan = {"meta": {}}


class TestTheFrameCarriesTheQualifier:
    """A widening is part of the restriction, not a separate fact.

    The scope line is built from the FRAME, and the frame outlives the build:
    it is what the next turn reads and what the payload serialises. When it
    dropped `widened`, the strip above the table said "Stage 2" over rows the
    sentence below it correctly called "Stage 2 or worse" — the same
    population described two ways, one screen apart.
    """

    def test_a_widened_restriction_reaches_the_frame(self):
        frame = sc.frame_of(_Build([("ifrs9_stage", "2")],
                                   [_Widened("ifrs9_stage", "2", "gte")]))
        assert frame.filters == [
            {"field": "ifrs9_stage", "value": "2", "op": "gte"}]

    def test_an_exact_restriction_records_no_qualifier(self):
        frame = sc.frame_of(_Build([("ifrs9_stage", "2")]))
        assert frame.filters == [{"field": "ifrs9_stage", "value": "2"}]

    def test_the_line_says_or_worse(self):
        frame = sc.frame_of(_Build([("ifrs9_stage", "2")],
                                   [_Widened("ifrs9_stage", "2", "gte")]))
        assert frame.line().startswith("Stage 2 or worse")

    def test_only_the_widened_restriction_is_qualified(self):
        frame = sc.frame_of(
            _Build([("ifrs9_stage", "2"), ("sector", "Shipping")],
                   [_Widened("ifrs9_stage", "2", "gte")]))
        assert frame.line().startswith("Stage 2 or worse, Shipping")

    def test_the_qualifier_survives_serialisation(self):
        # The frame crosses a turn boundary as a dict. A qualifier that does
        # not survive `to_dict` is a qualifier the next turn has lost.
        frame = sc.frame_of(_Build([("ifrs9_stage", "2")],
                                   [_Widened("ifrs9_stage", "2", "gte")]))
        restored = sc.ScopeFrame(filters=frame.to_dict()["filters"])
        assert restored.line().startswith("Stage 2 or worse")

    def test_the_frame_and_the_assembly_prose_agree(self):
        build = _Build([("ifrs9_stage", "2")],
                       [_Widened("ifrs9_stage", "2", "gte")])
        frame = sc.frame_of(build)
        prose = asm._scope_phrase(build.filters, build.widened)
        assert frame.line().startswith(prose)
