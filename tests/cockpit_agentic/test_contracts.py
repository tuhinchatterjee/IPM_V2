"""The typed contracts fail loudly at the boundary. Specification section 13."""

from __future__ import annotations

import pytest

from backend.cockpit_agentic import contracts as C

# ---- the repair-ownership rule, section 7.6A ------------------------------

def test_creditprobe_cannot_author_a_submission():
    step = C.ExecutionStep(step_id="s1", language="sql", code="SELECT 1")
    with pytest.raises(C.ContractError) as e:
        C.ExecutionSubmission(submission_id="sub-1", plan_id="p1",
                              analysis_round=1, submission_number=1,
                              steps=[step], authored_by="creditprobe")
    assert "sole owner" in str(e.value)


def test_a_revision_must_carry_opus_authored_code():
    with pytest.raises(C.ContractError) as e:
        C.AnalysisReviewDecision(decision=C.REVISE_ANALYSIS)
    assert "CreditProbe does not write it" in str(e.value)


def test_a_failure_packet_must_carry_the_exact_failed_code():
    """Section 8.1: a request id or schema hash alone is NOT memory."""
    with pytest.raises(C.ContractError) as e:
        C.ExecutionFailurePacket(
            request_id="r", plan_id="p", analysis_round=1, submission_id="s",
            submission_number=1, failing_step_id="x", phase="binding",
            language="sql", category=C.UNRESOLVED_FIELD, message="m",
            submitted_code="")
    assert "error-only retry" in str(e.value)


def test_security_failures_are_not_repairable():
    for category in (C.OUT_OF_SCOPE_ACCESS, C.PERMISSION_DENIED,
                     C.UNSAFE_OPERATION):
        packet = C.ExecutionFailurePacket(
            request_id="r", plan_id="p", analysis_round=1, submission_id="s",
            submission_number=1, failing_step_id="x", phase="validation",
            language="sql", category=category, message="m",
            submitted_code="SELECT * FROM ews_alerts")
        assert packet.repairable is False, (
            "section 8.3: security and out-of-domain requests fail closed "
            "immediately; five attempts are not spent on a workaround")


# ---- the functionality gate, section 6.2 ----------------------------------

def test_a_tie_is_not_a_silent_cockpit_execution():
    tie = C.FunctionalityDecision(
        decision=C.CLARIFY_FUNCTIONALITY,
        clarification_question="stored rating, or a new score?",
        scores=[C.SuitabilityScore("cockpit", 70, "a"),
                C.SuitabilityScore("credit_scoring", 70, "b")])
    assert tie.uniquely_highest_cockpit() is False
    assert tie.may_execute is False


def test_a_redirect_must_name_a_destination_and_a_reason():
    with pytest.raises(C.ContractError):
        C.FunctionalityDecision(decision=C.REDIRECT)
    with pytest.raises(C.ContractError):
        C.FunctionalityDecision(decision=C.REDIRECT,
                                referral_destination="ews")


def test_at_most_three_alternatives():
    alts = [C.AlternativeQuestion(question=f"q{i}", required_fields=["pd_pit_12m"])
            for i in range(4)]
    with pytest.raises(C.ContractError):
        C.FunctionalityDecision(decision=C.REDIRECT, referral_destination="ews",
                                referral_reason="r", alternatives=alts)


def test_an_alternative_that_names_no_field_is_refused():
    """Section 6.3: each suggestion must be feasible against the actual
    catalog. One that cannot be shown feasible is worse than none."""
    with pytest.raises(C.ContractError) as e:
        C.AlternativeQuestion(question="Have a look at the portfolio")
    assert "unanswerable suggestion" in str(e.value)


# ---- the catalog, section 4 -----------------------------------------------

def test_an_unexpanded_placeholder_never_reaches_the_catalog():
    with pytest.raises(C.ContractError):
        C.CockpitFieldSpec(name="{type}_net_value_rcy", relation="r",
                           label="l", definition="d", dtype="float")


def test_a_field_without_a_definition_is_refused():
    with pytest.raises(C.ContractError):
        C.CockpitFieldSpec(name="pd_pit_12m", relation="r", label="l",
                           definition="", dtype="float")


# ---- the registry, section 6.1 --------------------------------------------

def test_a_disabled_functionality_offers_no_link_and_says_why():
    with pytest.raises(C.ContractError):
        C.FunctionalityRegistryEntry(
            functionality_id="credit_scoring", ui_label="Credit Scoring",
            description="d", owns=(), excludes=(), supported_actions=(),
            examples=(), counterexamples=(), data_domain="", enabled=False,
            route="/credit-scoring")
    with pytest.raises(C.ContractError):
        C.FunctionalityRegistryEntry(
            functionality_id="credit_scoring", ui_label="Credit Scoring",
            description="d", owns=(), excludes=(), supported_actions=(),
            examples=(), counterexamples=(), data_domain="", enabled=False,
            route="", unavailable_reason="")


# ---- artifacts, section 10.4 ----------------------------------------------

def test_artifacts_are_validated_on_fetch_not_only_on_creation():
    manifest = C.ArtifactManifest(request_id="r")
    manifest.add(C.Artifact(artifact_id="a1", kind="table",
                            domain_id="corporate_cockpit", tenant_id="t1",
                            dataset_release_id="rel-1", step_id="s",
                            row_count=1, byte_size=10))
    with pytest.raises(C.ContractError):
        manifest.get("forged", tenant_id="t1", dataset_release_id="rel-1")
    with pytest.raises(C.ContractError):
        manifest.get("a1", tenant_id="other", dataset_release_id="rel-1")
    with pytest.raises(C.ContractError) as e:
        manifest.get("a1", tenant_id="t1", dataset_release_id="rel-2")
    assert "never silently mixed" in str(e.value)


def test_an_artifact_outside_the_domain_cannot_exist():
    with pytest.raises(C.ContractError):
        C.Artifact(artifact_id="a", kind="table", domain_id="ews",
                   tenant_id="t", dataset_release_id="r", step_id="s",
                   row_count=0, byte_size=0)


# ---- the question, sections 7.2 and 7.3 -----------------------------------

def test_a_failed_pass_one_preserves_the_raw_question():
    cleaned = C.CleanedQuestion(original_text="कितना ECL बढ़ा?",
                                detected_language="hi", english_text="")
    assert cleaned.failed is True
    assert cleaned.english_text == "कितना ECL बढ़ा?"


def test_an_explicit_instruction_overrides_an_inherited_filter():
    q = C.NormalizedQuestion(
        business_question="and now for Construction",
        explicit_scope={"sector": "Construction"},
        inherited_scope={"sector": "Real Estate", "quarter": "2026Q2"})
    assert q.effective_scope == {"sector": "Construction",
                                 "quarter": "2026Q2"}


def test_a_chart_specification_is_declarative_only():
    with pytest.raises(C.ContractError):
        C.AnswerChart(kind="<script>alert(1)</script>", title="t")
