"""
Raw feedback cannot change production. §11, proved rather than promised.

The rule
---------
    RAW FEEDBACK CANNOT MODIFY: Assurance status; Assurance score; Accuracy
    score; coverage; critical checks; plan fingerprint; result; certification;
    teaching release; production prompts; routing policy; model selection;
    ontology; methods.

Why a module rather than a paragraph
--------------------------------------
Because the rule is one refactor away from being false at any moment, and the
failure is silent. Somebody adds a "trending down, lower the confidence" line
because it seems obviously right; nothing breaks; and six months later an
Assurance score is a popularity measure. The product would look identical
either way, and the difference is the whole reason the score is worth having.

So the rule is code. `PROTECTED` names what feedback may not touch,
`sources()` names the modules feedback is allowed to reach at all, and
`audit()` reads the source of the feedback path and reports every write into a
protected name. The test suite runs `audit()` and fails on any finding, which
makes the rule enforceable by somebody who has never read this docstring.

What this does NOT claim
-------------------------
It is a static check over named modules and it can be defeated by anybody
determined to defeat it — `setattr(record, "overall_" + "status", ...)` would
pass. It is a guard against the honest mistake, which is the one that actually
happens, and it is paired with runtime tests that take a real Assurance record
and a real feedback event and assert the record is byte-identical afterwards.
Between them: the static check catches the line somebody adds, and the runtime
check catches the effect if the line gets past it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GUARD_VERSION = "1.0.0"

#: Modules that OWN protected state. The feedback path may not import any of
#: them, and the ban is the strongest part of this guard: you cannot mutate an
#: Assurance record you never imported.
#:
#: §35 asks for a link from a Feedback Event to an Assurance Record, and the
#: link is an ID string. That is the whole point — the feedback path names the
#: record and cannot reach it.
FORBIDDEN_IMPORTS: dict[str, str] = {
    "backend.assurance.store": "writes and supersedes Assurance Records",
    "backend.assurance.record": "computes the Assurance status and score",
    "backend.assurance.collect": "decides which Assurance checks ran",
    "backend.teaching.release": "decides which teaching cases production may "
                                "retrieve",
    "backend.intelligence_release": "the active intelligence release",
    "backend.orchestration.routing": "the routing policy and model route",
    "backend.orchestration.planner": "the production plan",
    "backend.semantics.ontology": "the governed ontology",
    "backend.llm.config": "which model serves which role",
    "backend.llm.roles": "which model serves which role",
}

#: Attribute and dict-key names that unambiguously mean protected state.
#:
#: Deliberately narrow. An earlier version listed `result`, `rows`, `model`,
#: `method` and `fingerprint`, which are also the names of ordinary local
#: variables and ordinary fields on the feedback objects themselves — so the
#: guard reported twelve findings on a service layer that touches nothing, and
#: a guard that cries wolf gets switched off. Every name here is one that
#: appears in this codebase ONLY as protected state.
PROTECTED: dict[str, tuple[str, ...]] = {
    "Assurance status": ("overall_status", "assurance_status"),
    "Assurance score": ("overall_score", "assurance_score", "score_pct"),
    "Accuracy score": ("accuracy_score", "accuracy_pct",
                       "independent_accuracy"),
    "coverage": ("coverage_pct",),
    "critical checks": ("critical_failures", "critical_checks",
                        "critical_not_available"),
    "plan fingerprint": ("plan_fingerprint",),
    "certification": ("certification", "certification_state"),
    "teaching release": ("teaching_release", "teaching_release_id"),
    "production prompts": ("system_prompt", "prompt_template",
                           "production_prompt"),
    "routing policy": ("routing_policy", "model_route"),
    "model selection": ("model_id", "model_role"),
    "ontology": ("ontology_version",),
    "methods": ("method_version", "method_definition"),
}

PROTECTED_NAMES: frozenset[str] = frozenset(
    name for names in PROTECTED.values() for name in names)

#: The modules the feedback path is made of. Everything a user's rating
#: touches, directly or through the service layer, on the way to storage.
FEEDBACK_MODULES: tuple[str, ...] = (
    "backend/learning/feedback.py",
    "backend/learning/observation.py",
    "backend/learning/candidate.py",
    "backend/learning/preference.py",
    "backend/learning/release.py",
    "backend/learning/replay.py",
    "backend/learning/models.py",
    "backend/services/learning.py",
    "backend/api/routers/learning.py",
)

#: Classes that DESCRIBE rather than decide. A feedback event records which
#: plan fingerprint and which assurance record an answer was produced under —
#: that is the link that makes it reproducible, and the opposite of modifying
#: them. So populating a field on one of these is permitted.
DESCRIBING: frozenset[str] = frozenset({
    "FeedbackEvent", "Observation", "CandidateCase", "Correction",
    "Satisfaction", "Preference", "LearningRelease", "Metrics", "Run",
    "CaseReplay", "AxisResult", "TrainingRun", "Split",
})

#: The marker that exempts one line, in the source, at the point of the write.
#:
#: There is one legitimate shape the class-name rule cannot see: a module-level
#: function that copies a describing object onto its database row —
#: `row.teaching_release_id = release.teaching_release_id`, which RECORDS which
#: teaching release a learning release was built against and does not touch the
#: teaching release at all.
#:
#: Making that an exemption the author has to write, on the line, with a
#: reason, is better than widening the rule until it stops firing. An
#: exemption is greppable, it appears in the guard's own report, and somebody
#: reviewing this file can see every one of them at once.
EXEMPTION = "# guard: describing"


@dataclass
class Finding:
    """One write into a protected name, in the feedback path."""

    module: str
    line: int
    target: str
    protects: str
    source: str

    def sentence(self) -> str:
        return (f"{self.module}:{self.line} reaches {self.target!r} — "
                f"{self.protects}. §11 forbids raw feedback from modifying "
                f"it.\n    {self.source.strip()}")

    def to_dict(self) -> dict[str, Any]:
        return {"module": self.module, "line": self.line,
                "target": self.target, "protects": self.protects,
                "source": self.source.strip(),
                "explanation": self.sentence()}


def _protects(name: str) -> str:
    for label, names in PROTECTED.items():
        if name in names:
            return label
    return ""


class _Walker(ast.NodeVisitor):
    """Every assignment in one module, checked against `PROTECTED`."""

    def __init__(self, module: str, lines: list[str]) -> None:
        self.module = module
        self.lines = lines
        self.findings: list[Finding] = []
        self.exemptions: list[tuple[int, str]] = []
        self._class: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._class.append(node.name)
        self.generic_visit(node)
        self._class.pop()

    def _describing(self) -> bool:
        return bool(self._class) and self._class[-1] in DESCRIBING

    def _exempt(self, line: int) -> bool:
        """Whether this exact line carries an explicit, reasoned exemption."""
        if line > len(self.lines):
            return False
        source = self.lines[line - 1]
        if EXEMPTION not in source:
            return False
        after = source.split(EXEMPTION, 1)[1].strip(" :—-")
        if after:
            self.exemptions.append((line, after))
            return True
        return False

    def _check(self, target: ast.expr, node: ast.stmt) -> None:
        name = ""
        if isinstance(target, ast.Attribute):
            name = target.attr
        elif isinstance(target, ast.Subscript):
            key = target.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                name = key.value
        if not name:
            return
        protects = _protects(name)
        if not protects or self._describing() or self._exempt(node.lineno):
            return
        line = node.lineno
        self.findings.append(Finding(
            module=self.module, line=line, target=name, protects=protects,
            source=self.lines[line - 1] if line <= len(self.lines) else ""))

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for target in node.targets:
            self._check(target, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self._check(node.target, node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self._check(node.target, node)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # `setattr(x, "overall_status", ...)` is an assignment wearing a hat.
        if (isinstance(node.func, ast.Name) and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            name = node.args[1].value
            protects = _protects(name)
            if protects and not self._describing():
                line = node.lineno
                self.findings.append(Finding(
                    module=self.module, line=line, target=name,
                    protects=protects,
                    source=(self.lines[line - 1] if line <= len(self.lines)
                            else "")))
        self.generic_visit(node)


def imports(root: Path | None = None,
            modules: tuple[str, ...] = FEEDBACK_MODULES
            ) -> list[Finding]:
    """Any module in the feedback path that imports one that owns protected
    state.

    The strongest check here, and the cheapest: a path that never imports the
    Assurance store cannot write an Assurance record, whatever it does with
    the names it has. Nothing can be smuggled past it by aliasing, because the
    import IS what is checked.
    """
    base = root or Path(__file__).resolve().parents[2]
    out: list[Finding] = []
    for name in modules:
        path = base / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            found = ""
            if isinstance(node, ast.Import):
                found = next((a.name for a in node.names
                              if a.name in FORBIDDEN_IMPORTS), "")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in FORBIDDEN_IMPORTS:
                    found = module
                else:
                    found = next(
                        (f"{module}.{a.name}" for a in node.names
                         if f"{module}.{a.name}" in FORBIDDEN_IMPORTS), "")
            if not found:
                continue
            out.append(Finding(
                module=name, line=node.lineno, target=found,
                protects=FORBIDDEN_IMPORTS[found],
                source=(lines[node.lineno - 1]
                        if node.lineno <= len(lines) else "")))
    return out


def audit(root: Path | None = None,
          modules: tuple[str, ...] = FEEDBACK_MODULES) -> list[Finding]:
    """Every write into a protected name, across the feedback path.

    A module that does not exist yet is not a finding — the path is built
    incrementally and an audit that failed on absence would have to be
    disabled during exactly the work it exists to police.
    """
    base = root or Path(__file__).resolve().parents[2]
    findings: list[Finding] = []
    for name in modules:
        path = base / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        walker = _Walker(name, text.splitlines())
        walker.visit(ast.parse(text))
        findings.extend(walker.findings)
        _EXEMPTIONS[name] = list(walker.exemptions)
    return findings


#: Every exemption the last audit saw, so the report can show them. An
#: exemption that nobody ever looks at is a hole with a comment on it.
_EXEMPTIONS: dict[str, list[tuple[int, str]]] = {}


def exemptions() -> list[dict[str, Any]]:
    """The reasoned exemptions in the feedback path, for review."""
    return [{"module": module, "line": line, "reason": reason}
            for module, found in sorted(_EXEMPTIONS.items())
            for line, reason in found]


#: Phrases a feedback path must not contain, because each one is a promise the
#: product cannot keep. §25: "Do not promise: CreditProbe has learned this
#: immediately."
FORBIDDEN_PROMISES: tuple[str, ...] = (
    "has learned", "have learned", "learned this", "will remember",
    "now knows", "updated the model", "retrained", "improved the model",
)


def _docstrings(tree: ast.AST) -> set[int]:
    """The line numbers every docstring occupies.

    A docstring that says "never promise the product has learned this" is not
    a promise, and the first version of this check fired on exactly that —
    which would have taught the next person to delete the explanation rather
    than to keep the rule.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            end = getattr(first, "end_lineno", first.lineno) or first.lineno
            lines.update(range(first.lineno, end + 1))
    return lines


def promises(root: Path | None = None,
             modules: tuple[str, ...] = FEEDBACK_MODULES
             ) -> list[tuple[str, int, str]]:
    """Anywhere the feedback path claims, to a user, to have learned.

    Checked over the STRING LITERALS the code could return rather than over
    the source text, because a docstring explaining the rule and a constant
    breaking it look the same to a line-based search — and the first version
    of this check reported the paragraph forbidding the promise. Comments and
    docstrings are excluded; anything the code could hand to a user is not.
    """
    base = root or Path(__file__).resolve().parents[2]
    pattern = re.compile("|".join(re.escape(p) for p in FORBIDDEN_PROMISES),
                         re.IGNORECASE)
    out: list[tuple[str, int, str]] = []
    for name in modules:
        path = base / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        skip = _docstrings(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or node.lineno in skip:
                continue
            if pattern.search(node.value):
                out.append((name, node.lineno, node.value.strip()[:200]))
    return out


@dataclass
class Report:
    """What the guard found, for the audit surface and for the test."""

    findings: list[Finding] = field(default_factory=list)
    promised: list[tuple[str, int, str]] = field(default_factory=list)
    exempted: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings and not self.promised

    def sentence(self) -> str:
        if self.ok:
            return (
                f"No path from user feedback writes to any of the "
                f"{len(PROTECTED)} things §11 protects, and nothing in the "
                "feedback path claims to have learned anything.")
        parts = []
        if self.findings:
            parts.append(f"{len(self.findings)} write(s) into protected "
                         "state: " + "; ".join(f.sentence()
                                               for f in self.findings[:5]))
        if self.promised:
            parts.append(
                f"{len(self.promised)} promise(s) of immediate learning: "
                + "; ".join(f"{m}:{n}" for m, n, _ in self.promised[:5]))
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok,
                "protected": {k: list(v) for k, v in PROTECTED.items()},
                "forbidden_imports": dict(FORBIDDEN_IMPORTS),
                "modules": list(FEEDBACK_MODULES),
                "exemptions": list(self.exempted),
                "findings": [f.to_dict() for f in self.findings],
                "promises": [{"module": m, "line": n, "source": s}
                             for m, n, s in self.promised],
                "explanation": self.sentence(),
                "version": GUARD_VERSION}


def report(root: Path | None = None) -> Report:
    """The whole §11 check, in one object."""
    found = [*imports(root), *audit(root)]
    return Report(findings=found, promised=promises(root),
                  exempted=exemptions())


__all__ = ["DESCRIBING", "EXEMPTION", "FEEDBACK_MODULES",
           "FORBIDDEN_IMPORTS", "FORBIDDEN_PROMISES", "Finding",
           "GUARD_VERSION", "PROTECTED", "PROTECTED_NAMES", "Report", "audit",
           "exemptions", "imports", "promises", "report"]
