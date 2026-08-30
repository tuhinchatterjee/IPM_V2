"""Whether a receiver can run what a package carries. §17.

An incoming Brain was built somewhere else, against a different catalogue, a
different set of installed modules, possibly a newer version of the product.
§17's requirement is not "refuse it" - it is that a user may import a package
into an inactive state, see exactly what would and would not work, and be
shown what would become active once the missing piece arrives.

The failure this prevents is the quiet one. A package carrying a method the
receiver has no dataset for could be imported, marked installed, and then
never run - and nothing on any screen would say why the thing somebody was
promised never appeared. So every unsupported component gets a NAMED reason
from §17's list, and stays visibly DORMANT rather than silently absent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

COMPATIBILITY_VERSION = "1.0.0"

# §17's reasons, verbatim. A component is never "unsupported"; it is
# unsupported FOR one of these reasons, which is what tells a receiver
# whether installing something would fix it.
MISSING_MODULE = "MISSING MODULE"
UNSUPPORTED_SCHEMA = "UNSUPPORTED SCHEMA"
NEWER_POLICY_VERSION = "NEWER POLICY VERSION"
UNKNOWN_METHOD = "UNKNOWN METHOD"
UNKNOWN_AGENT = "UNKNOWN AGENT"
UNKNOWN_VISUALIZATION = "UNKNOWN VISUALIZATION"
UNKNOWN_LANGUAGE = "UNKNOWN LANGUAGE"
UNKNOWN_SCOPE = "UNKNOWN SCOPE"
MISSING_DATA_CONTRACT = "MISSING DATA CONTRACT"
MISSING_RELATIONSHIP = "MISSING RELATIONSHIP"
APP_TOO_OLD = "APP TOO OLD"

REASONS: tuple[str, ...] = (
    MISSING_MODULE, UNSUPPORTED_SCHEMA, NEWER_POLICY_VERSION,
    UNKNOWN_METHOD, UNKNOWN_AGENT, UNKNOWN_VISUALIZATION, UNKNOWN_LANGUAGE,
    UNKNOWN_SCOPE, MISSING_DATA_CONTRACT, MISSING_RELATIONSHIP,
    APP_TOO_OLD,
)

#: Which reasons a receiver could fix by installing or upgrading something.
#: The others are facts about the package.
FIXABLE: frozenset[str] = frozenset({
    MISSING_MODULE, UNKNOWN_METHOD, UNKNOWN_AGENT, UNKNOWN_VISUALIZATION,
    MISSING_DATA_CONTRACT, MISSING_RELATIONSHIP, APP_TOO_OLD,
})


@dataclass
class Receiver:
    """What this installation actually has. Read, not assumed."""

    app_version: str = ""
    modules: frozenset[str] = frozenset()
    datasets: frozenset[str] = frozenset()
    relationships: frozenset[str] = frozenset()
    methods: frozenset[str] = frozenset()
    agents: frozenset[str] = frozenset()
    visualizations: frozenset[str] = frozenset()
    languages: frozenset[str] = frozenset({"en"})
    scopes: frozenset[str] = frozenset({"CORPORATE", "RETAIL", "NONE"})
    ontology_version: str = ""
    package_schema_version: str = ""

    @classmethod
    def here(cls) -> Receiver:
        """This installation, from its live registries."""
        from backend.agentic import registry
        from backend.brain.pack import PACKAGE_SCHEMA_VERSION
        from backend.data_access.catalog import get_catalog
        from backend.semantics import ontology
        from backend.services.relationships import GOVERNED_RELATIONSHIPS

        catalogue = get_catalog()
        datasets = {d.name for d in catalogue.all()}
        edges = {f"{r.from_dataset}->{r.to_dataset}"
                 for r in GOVERNED_RELATIONSHIPS}
        return cls(
            app_version=_app_version(),
            modules=frozenset({
                "ask", "investigations", "projects", "data-builder",
                "studio", "engine", "agentic", "assurance", "feedback",
                "learning", "regulatory", "early-warning", "stress",
                "lenses", "playbooks", "exports", "workflow",
                # §A8. Registered here rather than in a second mechanism: a
                # package that needs the Retail Scorecard module and lands
                # somewhere without it produces MISSING MODULE like any
                # other, and there is one place to keep correct.
                "retail-scorecard",
            }),
            datasets=frozenset(datasets),
            relationships=frozenset(edges),
            methods=frozenset(),
            agents=frozenset(a.agent_id for a in registry.AGENTS),
            visualizations=frozenset({
                "bar", "line", "share", "value", "table", "waterfall",
                "scatter", "heatmap", "metrics",
            }),
            ontology_version=getattr(ontology, "ONTOLOGY_VERSION", ""),
            package_schema_version=PACKAGE_SCHEMA_VERSION,
        )


def _app_version() -> str:
    """This installation's version, from the build stamp.

    Falls back to "0.0.0" rather than raising: a missing stamp makes every
    version comparison conservative, which reports a package as needing a
    newer app than it does. That errs towards refusing to activate, which is
    the right direction for a value nobody can read.
    """
    try:
        from backend import build_info

        return str(getattr(build_info, "VERSION", "") or "0.0.0")
    except Exception:  # noqa: BLE001 - a missing stamp is not a crash
        return "0.0.0"


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "0").replace("-", ".").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts or [0])


@dataclass
class Finding:
    """One component the receiver cannot run, and why."""

    kind: str
    name: str
    reason: str
    detail: str = ""

    @property
    def fixable(self) -> bool:
        return self.reason in FIXABLE

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "reason": self.reason,
                "detail": self.detail, "fixable": self.fixable,
                "would_activate_if_fixed": self.fixable}


@dataclass
class Report:
    """§17's compatibility report."""

    compatible: bool = True
    findings: list[Finding] = field(default_factory=list)
    receiver_app_version: str = ""
    package_minimum_version: str = ""

    @property
    def dormant(self) -> list[Finding]:
        """What would work once the receiver installs the missing piece."""
        return [f for f in self.findings if f.fixable]

    @property
    def incompatible(self) -> list[Finding]:
        return [f for f in self.findings if not f.fixable]

    def summary(self) -> str:
        if not self.findings:
            return "every component in this package can run here"
        parts = []
        if self.dormant:
            parts.append(
                f"{len(self.dormant)} component(s) would activate once the "
                "missing module, dataset or relationship is installed")
        if self.incompatible:
            parts.append(
                f"{len(self.incompatible)} component(s) cannot run here at "
                "all")
        return "; ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "compatible": self.compatible,
            "receiver_app_version": self.receiver_app_version,
            "package_minimum_version": self.package_minimum_version,
            "summary": self.summary(),
            "findings": [f.to_dict() for f in self.findings],
            "dormant": [f.to_dict() for f in self.dormant],
            "incompatible": [f.to_dict() for f in self.incompatible],
            "would_activate_if_installed": [
                f.name for f in self.dormant],
        }


def check(manifest: Any, receiver: Receiver | None = None, *,
          declared: dict[str, list[str]] | None = None) -> Report:
    """What this receiver can and cannot run from this package.

    `declared` lists the component names the package carries, by kind. It
    comes from the package's own contents rather than from the manifest's
    claims - a manifest saying it carries three methods and an archive
    holding four is a package whose manifest is wrong, and checking the
    manifest would miss the fourth.
    """
    here = receiver or Receiver.here()
    declared = declared or {}
    report = Report(receiver_app_version=here.app_version,
                    package_minimum_version=getattr(
                        manifest, "minimum_app_version", ""))

    minimum = getattr(manifest, "minimum_app_version", "")
    if minimum and _version_tuple(here.app_version) < _version_tuple(minimum):
        report.findings.append(Finding(
            "package", getattr(manifest, "brain_name", "package"),
            APP_TOO_OLD,
            f"this installation is {here.app_version} and the package needs "
            f"at least {minimum}"))

    package_schema = getattr(manifest, "package_schema_version", "")
    if package_schema and _version_tuple(package_schema) > _version_tuple(
            here.package_schema_version):
        report.findings.append(Finding(
            "package", "package_schema_version", UNSUPPORTED_SCHEMA,
            f"the package is schema {package_schema} and this installation "
            f"reads {here.package_schema_version}"))

    for module in getattr(manifest, "required_modules", ()) or ():
        if module not in here.modules:
            report.findings.append(Finding(
                "module", module, MISSING_MODULE,
                f"the package requires the {module} module, which is not "
                "installed here"))

    for language in getattr(manifest, "supported_languages", ()) or ():
        if language not in here.languages:
            report.findings.append(Finding(
                "language", language, UNKNOWN_LANGUAGE,
                f"content in {language} cannot be shown by this "
                "installation"))

    for scope in getattr(manifest, "supported_scopes", ()) or ():
        if scope and scope not in here.scopes:
            report.findings.append(Finding(
                "scope", scope, UNKNOWN_SCOPE,
                f"'{scope}' is not a portfolio scope this installation "
                "recognises"))

    for name in declared.get("methods", []):
        if here.methods and name not in here.methods:
            report.findings.append(Finding(
                "method", name, UNKNOWN_METHOD,
                "the package carries a method definition this installation "
                "does not have"))

    for name in declared.get("agents", []):
        if name not in here.agents:
            report.findings.append(Finding(
                "agent", name, UNKNOWN_AGENT,
                f"the package assigns work to '{name}', which is not in "
                "this Agent Registry"))

    for name in declared.get("visualizations", []):
        if name not in here.visualizations:
            report.findings.append(Finding(
                "visualization", name, UNKNOWN_VISUALIZATION,
                f"'{name}' is not a chart this installation can draw"))

    for name in declared.get("datasets", []):
        if name not in here.datasets:
            report.findings.append(Finding(
                "dataset", name, MISSING_DATA_CONTRACT,
                f"the package expects the {name} dataset, which this "
                "catalogue does not publish"))

    for name in declared.get("relationships", []):
        if name not in here.relationships:
            report.findings.append(Finding(
                "relationship", name, MISSING_RELATIONSHIP,
                f"the package joins on {name}, which is not a governed "
                "relationship here"))

    incoming_ontology = getattr(manifest, "ontology_version", "")
    if incoming_ontology and here.ontology_version and _version_tuple(
            incoming_ontology) > _version_tuple(here.ontology_version):
        report.findings.append(Finding(
            "ontology", incoming_ontology, NEWER_POLICY_VERSION,
            f"the package was built against ontology {incoming_ontology} "
            f"and this installation runs {here.ontology_version}"))

    report.compatible = not report.incompatible
    return report
