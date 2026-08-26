"""
Typed conversation working memory — what the last turn left on the table.

The behaviour this replaces
---------------------------
`ConversationState` remembered analyses. It remembered the population, the
measures, the filters and the plan, and it made analytical follow-ups work. What
it did not remember was anything that was not an analysis, so a thread like

    "What fields are available in the ratings data?"     → 22 fields
    "Which of those fields are financial ratios?"        → ???

lost "those" completely. The first turn produced a **field set** and nothing
wrote it down; the second turn looked for a population of customers, found none,
and asked what "of those" referred to. The same hole swallowed "what is the
latest available period?" after a dataset answer, and "open the latest dataset"
after that.

So memory is typed. Every turn — analytical or not — leaves behind a
`ResultReference` saying *what kind of thing* the last answer was and what was
in it, and a referent resolves against that type rather than against an
assumption that the conversation is always about customers.

What a type buys
----------------
"Which of those are financial ratios?" is a **classification of a field set**.
"Which of those are Stage 2?" is a **filter on an entity set**. They are the
same English sentence and completely different operations, and the only thing
that distinguishes them is what the previous turn produced. With the type
written down, the distinction is a lookup; without it, it is a guess.

What is NOT remembered
----------------------
Rows of governed data. A field set carries field names, an entity set carries
identifiers, a tabular result carries its column names and a bounded sample of
identities. Figures are re-derived through the runtime on every turn, because an
answer assembled from remembered numbers is not a governed figure any more.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

DATASET_SET = "DATASET_SET"
FIELD_SET = "FIELD_SET"
RELATIONSHIP_SET = "RELATIONSHIP_SET"
ENTITY_SET = "ENTITY_SET"
METRIC_SET = "METRIC_SET"
METHOD_SET = "METHOD_SET"
TABULAR_RESULT = "TABULAR_RESULT"
SCALAR_RESULT = "SCALAR_RESULT"
CHART_RESULT = "CHART_RESULT"
PLAN_RESULT = "PLAN_RESULT"

RESULT_TYPES: tuple[str, ...] = (
    DATASET_SET, FIELD_SET, RELATIONSHIP_SET, ENTITY_SET, METRIC_SET,
    METHOD_SET, TABULAR_RESULT, SCALAR_RESULT, CHART_RESULT, PLAN_RESULT,
)

#: Types whose members are things a follow-up can filter, classify or count
#: without running an analysis. "Which of those fields are ratios?" is answered
#: from the remembered field set; "which of those customers are Stage 2?" is
#: not, because stage lives in governed data rather than in the catalogue.
METADATA_TYPES = frozenset({DATASET_SET, FIELD_SET, RELATIONSHIP_SET,
                            METHOD_SET})

#: How many members are carried. Enough for the largest dataset's field list and
#: for a top-200 ranking; beyond that a follow-up should re-derive rather than
#: work from a pinned list.
MAX_MEMBERS = 200

# ---------------------------------------------------------------------------
# Subject types
# ---------------------------------------------------------------------------

SUBJECT_DATASET = "DATASET"
SUBJECT_FIELD = "FIELD"
SUBJECT_DOMAIN = "DOMAIN"
SUBJECT_METHOD = "METHOD"
SUBJECT_CUSTOMER = "CUSTOMER"
SUBJECT_SECTOR = "SECTOR"
SUBJECT_PORTFOLIO = "PORTFOLIO"
SUBJECT_CONCEPT = "CONCEPT"


@dataclass
class Member:
    """One thing in a remembered set, in the words the answer used.

    `id` is what a plan would use; `label` is what the user saw. They differ
    often enough — `total_ecl` versus "Expected credit loss" — that carrying
    only one of them makes either the follow-up or the sentence wrong.
    """

    id: str
    label: str = ""
    #: Whatever the set's type makes useful: a field's unit and type, a
    #: dataset's grain, an entity's headline value.
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        if self.label and self.label != self.id:
            out["label"] = self.label
        if self.attributes:
            out["attributes"] = dict(self.attributes)
        return out

    @classmethod
    def from_dict(cls, raw: Any) -> Member:
        if isinstance(raw, str):
            return cls(id=raw, label=raw)
        raw = raw or {}
        return cls(id=str(raw.get("id") or ""),
                   label=str(raw.get("label") or raw.get("id") or ""),
                   attributes=dict(raw.get("attributes") or {}))


@dataclass
class ResultReference:
    """What the last answer was, typed, so a follow-up can point at it."""

    result_type: str = ""
    #: What the set is of — "fields in customer_ratings", "Real Estate
    #: customers". Used in the sentence a follow-up produces, so it has to read
    #: like something a person would say.
    description: str = ""
    members: list[Member] = field(default_factory=list)
    #: The dataset, method or analysis the set came out of.
    origin: str = ""
    #: Column names, for a tabular result.
    columns: list[str] = field(default_factory=list)
    #: Headline figures, for a scalar or tabular result.
    values: dict[str, Any] = field(default_factory=dict)
    #: The run this came from, so the Trace can be reached from a follow-up.
    run_id: int | None = None
    period: str = ""
    total: int = 0

    @property
    def empty(self) -> bool:
        return not self.result_type

    @property
    def is_metadata(self) -> bool:
        return self.result_type in METADATA_TYPES

    def ids(self) -> list[str]:
        return [m.id for m in self.members if m.id]

    def labels(self, limit: int = 5) -> list[str]:
        return [m.label or m.id for m in self.members[:limit]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_type": self.result_type,
            "description": self.description,
            "members": [m.to_dict() for m in self.members[:MAX_MEMBERS]],
            "origin": self.origin,
            "columns": list(self.columns),
            "values": dict(self.values),
            "run_id": self.run_id,
            "period": self.period,
            "total": self.total or len(self.members),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ResultReference:
        raw = raw or {}
        return cls(
            result_type=str(raw.get("result_type") or ""),
            description=str(raw.get("description") or ""),
            members=[Member.from_dict(m) for m in (raw.get("members") or [])],
            origin=str(raw.get("origin") or ""),
            columns=[str(c) for c in (raw.get("columns") or [])],
            values=dict(raw.get("values") or {}),
            run_id=raw.get("run_id"),
            period=str(raw.get("period") or ""),
            total=int(raw.get("total") or 0),
        )

    def describe(self) -> str:
        """One line for the prompt block and for a "carried forward" note."""
        if self.empty:
            return ""
        count = self.total or len(self.members)
        shown = ", ".join(self.labels(4))
        noun = _NOUN.get(self.result_type, "results")
        tail = f" ({shown}…)" if shown else ""
        origin = f" of {self.origin}" if self.origin else ""
        return f"{count} {noun}{origin}{tail}"


_NOUN = {
    DATASET_SET: "datasets",
    FIELD_SET: "fields",
    RELATIONSHIP_SET: "relationships",
    ENTITY_SET: "entities",
    METRIC_SET: "measures",
    METHOD_SET: "methods",
    TABULAR_RESULT: "rows",
    SCALAR_RESULT: "figures",
    CHART_RESULT: "rows",
    PLAN_RESULT: "plans",
}


# ---------------------------------------------------------------------------
# The working memory
# ---------------------------------------------------------------------------


@dataclass
class WorkingMemory:
    """What the conversation is currently about, whatever kind of thing it is.

    Kept alongside `ConversationState` rather than merged into it, because the
    two answer different questions. State says what the last *analysis* settled
    and is what a plan modification reads. This says what the last *turn*
    produced and is what a referent resolves against — including the many turns
    that are not analyses at all.
    """

    #: What the conversation is about. A dataset name, a sector, a concept.
    current_subject: str = ""
    current_subject_type: str = ""
    #: What is being done to the subject, where the request named one — the
    #: field being discussed, the method being explained.
    current_object: str = ""
    current_object_type: str = ""
    current_capability: str = ""
    #: What the last turn produced.
    result: ResultReference = field(default_factory=ResultReference)
    #: Datasets and domains the thread has touched, most recent first.
    datasets: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    #: The periods the last answer was about, and the one it settled on.
    periods: list[str] = field(default_factory=list)
    current_period: str = ""
    #: How the last answer was presented, so "show it as a graph" knows what it
    #: is changing.
    presentation: str = ""
    #: Sub-requests of a compound question that were not answered. Read by
    #: CORRECT_INCOMPLETE_RESPONSE so "you didn't answer my second question"
    #: does not require the user to restate it.
    outstanding: list[str] = field(default_factory=list)
    #: What the previous turn asked, in full. Kept so a correction can re-read
    #: the compound request rather than the fragment that followed it.
    last_question: str = ""

    # ---- reading ----------------------------------------------------------

    @property
    def empty(self) -> bool:
        return not self.current_subject and self.result.empty

    @property
    def has_members(self) -> bool:
        return bool(self.result.members)

    def subject_line(self) -> str:
        if not self.current_subject:
            return ""
        kind = (self.current_subject_type or "").lower()
        return f"{self.current_subject} ({kind})" if kind else self.current_subject

    # ---- writing ----------------------------------------------------------

    def remember(self, *, subject: str = "", subject_type: str = "",
                 capability: str = "", result: ResultReference | None = None,
                 datasets: list[str] | None = None,
                 domains: list[str] | None = None,
                 periods: list[str] | None = None,
                 period: str = "", presentation: str = "",
                 question: str = "") -> None:
        """Fold one turn in. Absent fields leave what was there alone.

        Deliberately additive. A metadata question mid-investigation should
        change what "those" points at without wiping the sector the thread has
        been about for six turns.
        """
        if subject:
            self.current_subject = subject
            self.current_subject_type = subject_type or self.current_subject_type
        if capability:
            self.current_capability = capability
        if result is not None and not result.empty:
            self.result = result
        for name in reversed(datasets or []):
            if name and name in self.datasets:
                self.datasets.remove(name)
            if name:
                self.datasets.insert(0, name)
        del self.datasets[8:]
        for name in domains or []:
            if name and name not in self.domains:
                self.domains.append(name)
        del self.domains[8:]
        if periods:
            self.periods = list(periods)
        if period:
            self.current_period = period
        if presentation:
            self.presentation = presentation
        if question:
            self.last_question = question

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_subject": self.current_subject,
            "current_subject_type": self.current_subject_type,
            "current_object": self.current_object,
            "current_object_type": self.current_object_type,
            "current_capability": self.current_capability,
            "result": self.result.to_dict(),
            "datasets": list(self.datasets),
            "domains": list(self.domains),
            "periods": list(self.periods),
            "current_period": self.current_period,
            "presentation": self.presentation,
            "outstanding": list(self.outstanding),
            "last_question": self.last_question,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> WorkingMemory:
        raw = raw or {}
        return cls(
            current_subject=str(raw.get("current_subject") or ""),
            current_subject_type=str(raw.get("current_subject_type") or ""),
            current_object=str(raw.get("current_object") or ""),
            current_object_type=str(raw.get("current_object_type") or ""),
            current_capability=str(raw.get("current_capability") or ""),
            result=ResultReference.from_dict(raw.get("result")),
            datasets=[str(d) for d in (raw.get("datasets") or [])],
            domains=[str(d) for d in (raw.get("domains") or [])],
            periods=[str(p) for p in (raw.get("periods") or [])],
            current_period=str(raw.get("current_period") or ""),
            presentation=str(raw.get("presentation") or ""),
            outstanding=[str(q) for q in (raw.get("outstanding") or [])],
            last_question=str(raw.get("last_question") or ""),
        )

    def brief(self) -> str:
        """The block a model is given so it can read a follow-up.

        Facts only, in the fewest tokens that carry them. No instructions: the
        system prompt says what to do with context, and repeating it here would
        double the cost of every turn to say something already said.
        """
        if self.empty:
            return ""
        lines: list[str] = ["CONVERSATION SO FAR"]
        if self.current_subject:
            lines.append(f"- currently about: {self.subject_line()}")
        if self.current_capability:
            lines.append(f"- last answered as: {self.current_capability}")
        if not self.result.empty:
            lines.append(f"- last result: {self.result.result_type} — "
                         f"{self.result.describe()}")
            if self.result.is_metadata and self.result.members:
                shown = ", ".join(m.id for m in self.result.members[:25])
                more = max(0, len(self.result.members) - 25)
                lines.append(f"  members: {shown}"
                             + (f" (+{more} more)" if more else ""))
        if self.current_period:
            lines.append(f"- period in view: {self.current_period}")
        if self.presentation:
            lines.append(f"- shown as: {self.presentation}")
        if self.outstanding:
            lines.append("- not yet answered from the previous request: "
                         + "; ".join(self.outstanding))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence and observation
# ---------------------------------------------------------------------------

#: Where the memory lives inside `Investigation.context`. A sibling of the
#: conversation state rather than part of it: the two are written by different
#: turns — every turn writes memory, only an analytical one settles state — and
#: merging them meant a metadata question wiped the population.
MEMORY_KEY = "working_memory"


def load(context: dict[str, Any] | None) -> WorkingMemory:
    return WorkingMemory.from_dict((context or {}).get(MEMORY_KEY))


def save(context: dict[str, Any] | None,
         memory: WorkingMemory) -> dict[str, Any]:
    return {**dict(context or {}), MEMORY_KEY: memory.to_dict()}


def observe(memory: WorkingMemory, answered: Any, run: Any = None) -> WorkingMemory:
    """Fold one answered turn into the memory.

    Never raises. A memory write that failed must not lose the answer the user
    is already reading — the worst case is a follow-up that has to be asked in
    full, which is where the product was before this existed.
    """
    try:
        return _observe(memory, answered, run)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not update the conversation working memory: %s", e)
        return memory


#: Where a compound question joins its second objective to its first.
#:
#: Deliberately narrow: the second clause has to START with an interrogative,
#: so "total EAD and ECL by sector" is one objective with two measures while
#: "what fields are in the ratings data, and which of them are ratios?" is two
#: objectives. Splitting on a bare "and" would turn every multi-measure request
#: into a half-answered one.
_OBJECTIVE_SPLIT = re.compile(
    r",?\s+(?:and|&)\s+(?=(?:which|what|who|whose|whom|when|where|why|how)\b)",
    re.I)


def objectives(question: str) -> list[str]:
    """The separate things a compound question asks for, in order.

    One entry for an ordinary question. Two or more when the sentence asks a
    second question that a single result cannot answer.
    """
    text = str(question or "").strip()
    if not text:
        return []
    parts = [p.strip(" ,.?!") for p in _OBJECTIVE_SPLIT.split(text)]
    return [p for p in parts if len(p.split()) >= 2] or [text.strip(" ,.?!")]


def _outstanding(question: str) -> list[str]:
    """The objectives beyond the first, which one answer cannot have covered.

    Recorded optimistically: a handler returns one result, so at most one
    objective was answered, and the trailing clauses are the candidates for
    "you didn't answer my second question". A false positive costs nothing —
    the only things that read this slot are a routing signal and the
    correction path, and both do the right thing with a clause that was in
    fact already answered.
    """
    parts = objectives(question)
    return parts[1:] if len(parts) > 1 else []


def _observe(memory: WorkingMemory, answered: Any,
             run: Any) -> WorkingMemory:

    reading = getattr(answered, "reading", None)
    intent = getattr(reading, "intent", "") if reading else ""
    memory.last_question = getattr(answered, "question", "") or memory.last_question

    # A turn that answered nothing settles nothing. It still records what was
    # asked, so a correction can re-read it.
    if getattr(answered, "clarification", "") or getattr(answered, "unsupported", ""):
        return memory

    result = getattr(answered, "result", None)
    runtime = getattr(answered, "runtime", None)

    if result is not None:
        reference = _from_handler(intent, result)
    elif runtime is not None:
        reference = _from_runtime(answered, runtime, run)
    else:
        return memory

    memory.outstanding = _outstanding(getattr(answered, "question", ""))
    memory.remember(
        subject=reference.origin or _subject_of(reading),
        subject_type=_subject_type(intent, reference),
        capability=intent,
        result=reference,
        datasets=_datasets(answered, runtime),
        period=reference.period,
        presentation=_presentation(answered),
        question=getattr(answered, "question", ""))
    return memory


def _from_handler(intent: str, result: Any) -> ResultReference:
    """What a metadata answer left behind, typed by which capability ran."""

    rows = list(getattr(result, "rows", []) or [])
    kind, key, label_key = _shape(intent, rows)

    members: list[Member] = []
    for row in rows[:MAX_MEMBERS]:
        if not isinstance(row, dict):
            continue
        ident = str(row.get(key) or "") if key else ""
        if not ident:
            continue
        members.append(Member(
            id=ident,
            label=str(row.get(label_key) or ident) if label_key else ident,
            attributes={k: v for k, v in row.items()
                        if k in _KEPT and v not in (None, "")}))

    origin = ""
    if kind == FIELD_SET and rows:
        origin = str(rows[0].get("dataset") or "")
    elif kind == DATASET_SET and len(rows) == 1:
        origin = str(rows[0].get("dataset") or "")
    elif kind == DATASET_SET and members:
        origin = members[0].id

    period = ""
    if rows and isinstance(rows[0], dict):
        period = str(rows[0].get("to") or rows[0].get("period") or "")

    return ResultReference(
        result_type=kind,
        description=str(getattr(result, "answer", ""))[:200],
        members=members, origin=origin,
        columns=[str(c.get("name") or c) for c in
                 (getattr(result, "columns", []) or [])],
        values=dict(getattr(result, "values", {}) or {}),
        period=period, total=len(rows))


def _from_runtime(answered: Any, runtime: Any, run: Any) -> ResultReference:
    """What an analysis left behind: the identities and the column names."""
    state = getattr(answered, "build", None)
    rows = list(getattr(runtime, "rows", []) or [])
    columns = [str(getattr(c, "name", c)) for c in
               (getattr(runtime, "columns", []) or [])]
    key = next((c for c in _IDENTITY if c in columns), "")

    members: list[Member] = []
    if key:
        seen: set[str] = set()
        for row in rows[:MAX_MEMBERS * 2]:
            ident = str(row.get(key) or "")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            members.append(Member(id=ident,
                                  label=str(row.get("borrower_name") or ident)))
            if len(members) >= MAX_MEMBERS:
                break

    return ResultReference(
        result_type=ENTITY_SET if key else TABULAR_RESULT,
        description=str(getattr(answered, "question", ""))[:200],
        members=members,
        origin=(getattr(state, "summary", "") or "")[:120],
        columns=columns,
        values=dict(getattr(runtime, "values", {}) or {}),
        run_id=getattr(run, "analysis_run_id", None),
        period=str(getattr(runtime, "period", "") or ""),
        total=len(rows))


def _shape(intent: str, rows: list[Any]) -> tuple[str, str, str]:
    """What kind of set this is, decided by the rows and only then the intent.

    The intent alone was wrong twice in one thread. "How many years of ratings
    history?" is read as DATA_QUALITY, which usually returns fields — but that
    question returns one dataset row, so keying on `field` found no members and
    an empty FIELD_SET overwrote the dataset the conversation was about. The
    rows know what they are; the intent only knows what they usually are.
    """
    keys: set[str] = set()
    for row in rows[:5]:
        if isinstance(row, dict):
            keys |= set(row)

    for kind, key, label_key in _BY_KEY:
        if key in keys:
            return kind, key, label_key

    return _SHAPE.get(intent, (TABULAR_RESULT, "", ""))


#: (result type, identifying row key, label key) — checked in this order, so a
#: field list that also names its dataset is a FIELD_SET rather than a
#: DATASET_SET.
_BY_KEY: tuple[tuple[str, str, str], ...] = (
    (FIELD_SET, "field", "business_name"),
    (METHOD_SET, "method", "name"),
    (RELATIONSHIP_SET, "step", "to"),
    (DATASET_SET, "dataset", "business_name"),
)

#: intent -> (result type, the row key that identifies a member, its label)
_SHAPE: dict[str, tuple[str, str, str]] = {
    "DATA_DISCOVERY": (DATASET_SET, "dataset", "business_name"),
    "DATA_INSPECTION": (DATASET_SET, "dataset", "business_name"),
    "DATA_DICTIONARY": (FIELD_SET, "field", "business_name"),
    "DATA_QUALITY": (FIELD_SET, "field", "business_name"),
    "DATA_RELATIONSHIP": (RELATIONSHIP_SET, "from", "to"),
    "METHOD_DISCOVERY": (METHOD_SET, "method", "name"),
    "METHOD_EXPLANATION": (METHOD_SET, "method", "name"),
}

#: Row keys worth carrying on a member. Anything that lets a follow-up
#: classify the set without going back to the catalogue.
_KEPT = frozenset({"unit", "type", "definition", "grain", "domain", "periods",
                   "from", "to", "business_name", "dataset", "cardinality",
                   "join", "fields", "match_rate"})

_IDENTITY = ("customer_id", "account_id", "borrower_id", "sector", "region",
             "segment")


def _subject_of(reading: Any) -> str:
    if reading is None:
        return ""
    datasets = list(getattr(reading, "datasets", ()) or ())
    if datasets:
        return datasets[0]
    concepts = list(getattr(reading, "concepts", ()) or ())
    return concepts[0] if concepts else ""


def _subject_type(intent: str, reference: ResultReference) -> str:
    if reference.result_type in (DATASET_SET,):
        return SUBJECT_DATASET
    if reference.result_type == FIELD_SET:
        return SUBJECT_DATASET
    if reference.result_type == METHOD_SET:
        return SUBJECT_METHOD
    if reference.result_type == ENTITY_SET:
        return SUBJECT_CUSTOMER
    return SUBJECT_CONCEPT


def _datasets(answered: Any, runtime: Any) -> list[str]:
    reading = getattr(answered, "reading", None)
    named = list(getattr(reading, "datasets", ()) or ()) if reading else []
    used = list(getattr(runtime, "datasets", ()) or []) if runtime else []
    return [str(d) for d in (named + used) if d]


def _presentation(answered: Any) -> str:
    continuation = getattr(answered, "continuation", None)
    return str(getattr(continuation, "presentation", "") or "")


__all__ = [
    "CHART_RESULT",
    "DATASET_SET",
    "ENTITY_SET",
    "FIELD_SET",
    "MAX_MEMBERS",
    "METADATA_TYPES",
    "METHOD_SET",
    "METRIC_SET",
    "PLAN_RESULT",
    "RELATIONSHIP_SET",
    "RESULT_TYPES",
    "SCALAR_RESULT",
    "SUBJECT_CONCEPT",
    "SUBJECT_CUSTOMER",
    "SUBJECT_DATASET",
    "SUBJECT_DOMAIN",
    "SUBJECT_FIELD",
    "SUBJECT_METHOD",
    "SUBJECT_PORTFOLIO",
    "SUBJECT_SECTOR",
    "TABULAR_RESULT",
    "MEMORY_KEY",
    "Member",
    "ResultReference",
    "WorkingMemory",
    "load",
    "observe",
    "save",
]
