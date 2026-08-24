"""
Data Builder API — self-service dataset onboarding.

Covers the whole workflow:

    domains -> datasets -> upload -> inspect -> map -> dictionary
            -> relationships -> validate -> publish -> versions

Every mutating endpoint declares the role it requires (see api/permissions.py).
Reading is open to any role; publishing is restricted to ADMIN and DATA_STEWARD.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.permissions import Principal, RequireDataSteward, RequirePublisher
from backend.config import settings
from backend.db.engine import SessionLocal
from backend.services import assistant, governance, harmonisation
from backend.services import data_builder as db_service
from backend.services.data_builder import DataBuilderError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/data-builder", tags=["data builder"])


def get_db() -> Session:
    """A transactional session per request, committed on success."""
    if not settings.has_database:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "database_not_configured",
                    "message": "Data Builder needs PostgreSQL. Start it with: docker compose up -d db"},
        )
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _fail(e: DataBuilderError, code: int = status.HTTP_400_BAD_REQUEST):
    return HTTPException(status_code=code,
                         detail={"error": "data_builder_error", "message": str(e)})


# ------------------------------------------------------------------- payloads


class DomainIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    owner: str = ""
    sort_order: int = 0


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=160,
                      description="Governed name: lower_snake_case.")
    domain: str
    business_name: str = ""
    purpose: str = ""
    grain: str = ""
    owner: str = ""
    period_field: str = ""
    primary_keys: list[str] = Field(default_factory=list)
    is_synthetic: bool = False


class MappingIn(BaseModel):
    source_column: str
    governed_field: str | None = None
    status: str = Field(description="mapped | unmapped | ignored | proposed")
    note: str = ""


class MappingsIn(BaseModel):
    mappings: list[MappingIn]


class FieldIn(BaseModel):
    name: str
    business_name: str = ""
    definition: str = ""
    data_type: str = "string"
    unit: str | None = None
    allowed_values: list[str] | None = None
    sensitivity: str = "internal"
    nullable: bool = True
    source_system: str = ""
    source_field: str = ""


class RelationshipIn(BaseModel):
    from_dataset: str
    from_field: str
    to_dataset: str
    to_field: str
    cardinality: str = "many_to_one"
    kind: str = Field(default="key", description="key | reporting_period")
    description: str = ""
    name: str = ""


# ------------------------------------------------------------------ serialise


def _dataset_out(dataset, session: Session) -> dict[str, Any]:
    return {
        "name": dataset.name,
        "domain": dataset.domain,
        "business_name": dataset.business_name,
        "purpose": dataset.purpose,
        "grain": dataset.grain,
        "owner": dataset.owner,
        "period_field": dataset.period_field,
        "primary_keys": dataset.primary_keys,
        "lifecycle": dataset.lifecycle,
        "source_type": dataset.source_type,
        "is_synthetic": dataset.is_synthetic,
        # The control plane, on every dataset: where it came from, what it
        # belongs with, and what it is the source of truth for.
        "origin": dataset.origin,
        "is_demo": dataset.origin == "demo",
        "dataset_family": dataset.dataset_family or dataset.name,
        "authoritative_for": list(dataset.authoritative_for or []),
        "published_version": dataset.published_version,
        "published_at": dataset.published_at.isoformat() if dataset.published_at else None,
        "field_count": len(dataset.fields),
        "upload_count": len(dataset.uploads),
        "storage_location": dataset.storage_location,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
    }


def _mapping_out(m) -> dict[str, Any]:
    return {
        "source_column": m.source_column,
        "governed_field": m.governed_field,
        "status": m.status,
        "confidence": m.confidence,
        "note": m.note,
    }


def _upload_out(u) -> dict[str, Any]:
    return {
        "id": u.id,
        "filename": u.filename,
        "file_format": u.file_format,
        "sheet_name": u.sheet_name,
        "raw_path": u.raw_path,
        "file_sha256": u.file_sha256,
        "size_bytes": u.size_bytes,
        "row_count": u.row_count,
        "column_count": u.column_count,
        "uploaded_at": u.uploaded_at.isoformat() if u.uploaded_at else None,
    }


# -------------------------------------------------------------------- domains


@router.get("/domains", summary="List data domains")
def list_domains(session: Session = Depends(get_db)) -> dict:
    domains = db_service.list_domains(session)
    return {"domains": [
        {"name": d.name, "description": d.description, "owner": d.owner,
         "sort_order": d.sort_order} for d in domains
    ]}


@router.post("/domains", summary="Create or update a data domain")
def upsert_domain(payload: DomainIn, session: Session = Depends(get_db),
                  principal: Principal = RequireDataSteward) -> dict:
    domain = db_service.upsert_domain(
        session, name=payload.name, description=payload.description,
        owner=payload.owner, sort_order=payload.sort_order,
    )
    return {"name": domain.name, "description": domain.description, "owner": domain.owner}


# ------------------------------------------------------------------- datasets


@router.get("/datasets", summary="List datasets")
def list_datasets(domain: str | None = None, lifecycle: str | None = None,
                  session: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    from backend.models.platform import DatasetDefinition

    stmt = select(DatasetDefinition).order_by(DatasetDefinition.name)
    if domain:
        stmt = stmt.where(DatasetDefinition.domain == domain)
    if lifecycle:
        stmt = stmt.where(DatasetDefinition.lifecycle == lifecycle)
    datasets = list(session.execute(stmt).scalars())
    return {"count": len(datasets), "datasets": [_dataset_out(d, session) for d in datasets]}


@router.post("/datasets", status_code=status.HTTP_201_CREATED, summary="Create a dataset")
def create_dataset(payload: DatasetIn, session: Session = Depends(get_db),
                   principal: Principal = RequireDataSteward) -> dict:
    try:
        dataset = db_service.create_dataset(
            session, name=payload.name, domain=payload.domain,
            business_name=payload.business_name, purpose=payload.purpose,
            grain=payload.grain, owner=payload.owner, period_field=payload.period_field,
            primary_keys=payload.primary_keys, is_synthetic=payload.is_synthetic,
        )
    except DataBuilderError as e:
        raise _fail(e) from e
    return _dataset_out(dataset, session)


@router.get("/datasets/{name}", summary="Dataset detail")
def get_dataset(name: str, session: Session = Depends(get_db)) -> dict:
    try:
        dataset = db_service.get_dataset(session, name)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e
    upload = db_service.latest_upload(session, dataset)
    return {
        **_dataset_out(dataset, session),
        "latest_upload": _upload_out(upload) if upload else None,
        "mappings": [_mapping_out(m) for m in db_service.get_mappings(session, dataset)],
        "fields": [
            {"name": f.name, "business_name": f.business_name, "definition": f.definition,
             "data_type": f.data_type, "unit": f.unit, "allowed_values": f.allowed_values,
             "sensitivity": f.sensitivity, "nullable": f.nullable,
             "source_system": f.source_system, "source_field": f.source_field}
            for f in sorted(dataset.fields, key=lambda x: x.name)
        ],
        "relationships": [
            {"name": r.name, "from_dataset": r.from_dataset, "from_field": r.from_field,
             "to_dataset": r.to_dataset, "to_field": r.to_field,
             "cardinality": r.cardinality, "kind": r.kind}
            for r in db_service.list_relationships(session, name)
        ],
    }


# --------------------------------------------------------------------- upload


@router.post("/datasets/{name}/upload", summary="Upload a source file (CSV, Excel or Parquet)")
async def upload(name: str, file: UploadFile = File(...), sheet_name: str | None = Form(None),
                 session: Session = Depends(get_db),
                 principal: Principal = RequireDataSteward) -> dict:
    """Store the file unchanged in the RAW layer, inspect it, and suggest mappings."""
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": "file_too_large",
                    "message": f"The file is larger than the {settings.max_upload_mb} MB limit."},
        )
    try:
        record = db_service.upload_file(
            session, dataset_name=name, content=content,
            filename=file.filename or "upload", sheet_name=sheet_name,
            uploaded_by=principal.user_id,
        )
    except DataBuilderError as e:
        raise _fail(e) from e
    dataset = db_service.get_dataset(session, name)
    return {
        "upload": _upload_out(record),
        "profile": record.profile,
        "suggested_mappings": [_mapping_out(m) for m in db_service.get_mappings(session, dataset)],
        "lifecycle": dataset.lifecycle,
    }


@router.get("/datasets/{name}/profile", summary="Inspection profile of the latest upload")
def get_profile(name: str, session: Session = Depends(get_db)) -> dict:
    try:
        dataset = db_service.get_dataset(session, name)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e
    upload = db_service.latest_upload(session, dataset)
    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_upload",
                    "message": f"No file has been uploaded for '{name}' yet."},
        )
    return {"dataset": name, "upload": _upload_out(upload), "profile": upload.profile}


# -------------------------------------------------------------------- mapping


@router.get("/datasets/{name}/mappings", summary="Current field mappings")
def get_mappings(name: str, session: Session = Depends(get_db)) -> dict:
    try:
        dataset = db_service.get_dataset(session, name)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e
    return {"dataset": name,
            "mappings": [_mapping_out(m) for m in db_service.get_mappings(session, dataset)]}


@router.put("/datasets/{name}/mappings", summary="Set field mappings")
def set_mappings(name: str, payload: MappingsIn, session: Session = Depends(get_db),
                 principal: Principal = RequireDataSteward) -> dict:
    try:
        mappings = db_service.set_mappings(
            session, name, [m.model_dump() for m in payload.mappings]
        )
    except DataBuilderError as e:
        raise _fail(e) from e
    dataset = db_service.get_dataset(session, name)
    return {"dataset": name, "lifecycle": dataset.lifecycle,
            "mappings": [_mapping_out(m) for m in mappings]}


# ----------------------------------------------------------------- dictionary


@router.put("/datasets/{name}/fields", summary="Create or update a data dictionary entry")
def upsert_field(name: str, payload: FieldIn, session: Session = Depends(get_db),
                 principal: Principal = RequireDataSteward) -> dict:
    try:
        field = db_service.upsert_field_definition(session, name, **payload.model_dump())
    except DataBuilderError as e:
        raise _fail(e) from e
    return {"dataset": name, "field": {"name": field.name, "business_name": field.business_name,
                                       "definition": field.definition, "data_type": field.data_type,
                                       "unit": field.unit, "sensitivity": field.sensitivity}}


@router.post("/datasets/{name}/fields/seed", summary="Seed dictionary entries from the mappings")
def seed_dictionary(name: str, session: Session = Depends(get_db),
                    principal: Principal = RequireDataSteward) -> dict:
    try:
        fields = db_service.seed_dictionary_from_mappings(session, name)
    except DataBuilderError as e:
        raise _fail(e) from e
    return {"dataset": name, "created": len(fields),
            "fields": [f.name for f in fields]}


# -------------------------------------------------------------- relationships


@router.get("/relationships", summary="List dataset relationships")
def list_relationships(dataset: str | None = None, session: Session = Depends(get_db)) -> dict:
    rels = db_service.list_relationships(session, dataset)
    return {"count": len(rels), "relationships": [
        {"id": r.id, "name": r.name, "from_dataset": r.from_dataset, "from_field": r.from_field,
         "to_dataset": r.to_dataset, "to_field": r.to_field, "cardinality": r.cardinality,
         "kind": r.kind, "description": r.description} for r in rels
    ]}


@router.post("/relationships", status_code=status.HTTP_201_CREATED,
             summary="Define a relationship between two datasets")
def add_relationship(payload: RelationshipIn, session: Session = Depends(get_db),
                     principal: Principal = RequireDataSteward) -> dict:
    try:
        rel = db_service.add_relationship(session, **payload.model_dump())
    except DataBuilderError as e:
        raise _fail(e) from e
    return {"id": rel.id, "name": rel.name, "from_dataset": rel.from_dataset,
            "from_field": rel.from_field, "to_dataset": rel.to_dataset,
            "to_field": rel.to_field, "kind": rel.kind}


# ----------------------------------------------------------- validate/publish


@router.post("/datasets/{name}/validate", summary="Run data quality checks")
def validate(name: str, session: Session = Depends(get_db),
             principal: Principal = RequireDataSteward) -> dict:
    try:
        return db_service.validate_dataset(session, name)
    except DataBuilderError as e:
        raise _fail(e) from e


@router.post("/datasets/{name}/publish", summary="Publish the dataset")
def publish(name: str, force: bool = False, session: Session = Depends(get_db),
            principal: Principal = RequirePublisher) -> dict:
    """Write the curated and analytics Parquet and record an immutable version.

    Only after this does the analytical engine see the dataset.
    """
    try:
        version = db_service.publish_dataset(
            session, name, published_by=principal.user_id, force=force
        )
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_409_CONFLICT) from e

    # Commit before refreshing: the catalogue reload opens its own session and
    # would not see an uncommitted dataset.
    session.commit()
    db_service.refresh_governed_catalog()

    return {
        "dataset": name, "version": version.version, "row_count": version.row_count,
        "field_count": version.field_count, "periods": version.periods,
        "analytics_path": version.analytics_path, "curated_path": version.curated_path,
        "quality_report": version.quality_report,
        "published_at": version.published_at.isoformat() if version.published_at else None,
        "message": f"'{name}' v{version.version} is published and available to the analytical engine.",
    }


@router.get("/datasets/{name}/versions", summary="Published versions of a dataset")
def list_versions(name: str, session: Session = Depends(get_db)) -> dict:
    try:
        versions = db_service.list_versions(session, name)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e
    return {"dataset": name, "count": len(versions), "versions": [
        {"version": v.version, "row_count": v.row_count, "field_count": v.field_count,
         "periods": v.periods, "analytics_path": v.analytics_path,
         "quality_report": v.quality_report,
         "published_at": v.published_at.isoformat() if v.published_at else None}
        for v in versions
    ]}


# =========================================================== the control plane
#
# Data Builder is not an inventory of files. It is where a bank says which
# dataset is the source of truth for a governed purpose, what belongs together,
# and what would break if something were removed. These endpoints are that.


class OriginIn(BaseModel):
    origin: str = Field(max_length=24, description="demo | client | supplementary")


class FamilyIn(BaseModel):
    family: str = Field(default="", max_length=160)


class AuthoritativeIn(BaseModel):
    purposes: list[str] = Field(
        default_factory=list,
        description="The governed purposes this dataset is the source of truth for.",
    )


class ReplaceIn(BaseModel):
    incoming: str = Field(min_length=1, max_length=160)
    acknowledge: bool = Field(
        default=False,
        description="Proceed even though the incoming dataset does not supply "
                    "everything the outgoing one does.",
    )


@router.post("/sync-bundled", summary="Register CreditProbe's bundled datasets for governance")
def sync_bundled(session: Session = Depends(get_db),
                 principal: Principal = RequireDataSteward) -> dict:
    """Bring the demonstration book into Data Builder so it can be governed.

    Idempotent. A dataset a steward has re-marked as client data is left alone.
    """
    return governance.sync_bundled_catalog(session)


@router.get("/control-plane", summary="What is powering CreditProbe right now")
def control_plane(session: Session = Depends(get_db)) -> dict:
    """Purpose by purpose: which dataset answers it, and is it demo data?"""
    return governance.control_plane(session)


@router.get("/families", summary="Dataset families")
def dataset_families(session: Session = Depends(get_db)) -> dict:
    return {"families": governance.families(session)}


@router.get("/datasets/{name}/used-by", summary="What depends on this dataset")
def dataset_used_by(name: str, session: Session = Depends(get_db)) -> dict:
    try:
        return governance.used_by(session, name).to_dict()
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e


@router.post("/datasets/{name}/origin", summary="Mark a dataset demo or client data")
def set_origin(name: str, payload: OriginIn, session: Session = Depends(get_db),
               principal: Principal = RequireDataSteward) -> dict:
    try:
        dataset = governance.set_origin(session, name, payload.origin)
    except DataBuilderError as e:
        raise _fail(e) from e
    return {"dataset": dataset.name, "origin": dataset.origin}


@router.post("/datasets/{name}/family", summary="Put a dataset in a family")
def set_family(name: str, payload: FamilyIn, session: Session = Depends(get_db),
               principal: Principal = RequireDataSteward) -> dict:
    try:
        dataset = governance.set_family(session, name, payload.family)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e
    return {"dataset": dataset.name, "dataset_family": dataset.dataset_family}


@router.post("/datasets/{name}/authoritative",
             summary="Declare which governed purposes this dataset answers")
def set_authoritative(name: str, payload: AuthoritativeIn,
                      session: Session = Depends(get_db),
                      principal: Principal = RequirePublisher) -> dict:
    """The moment client data replaces the demonstration book.

    Needs the publishing role, because every certified analysis reading that
    purpose follows this decision immediately.
    """
    try:
        return governance.set_authoritative(session, name, payload.purposes)
    except DataBuilderError as e:
        raise _fail(e) from e


@router.post("/datasets/{name}/archive", summary="Take a dataset out of service")
def archive_dataset(name: str, acknowledge: bool = False,
                    session: Session = Depends(get_db),
                    principal: Principal = RequirePublisher) -> dict:
    try:
        return governance.archive_dataset(session, name, acknowledge=acknowledge)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_409_CONFLICT) from e


@router.get("/datasets/{name}/compare/{incoming}",
            summary="Can one dataset stand in for another?")
def compare_datasets(name: str, incoming: str, session: Session = Depends(get_db)) -> dict:
    try:
        return governance.compare_schemas(session, name, incoming)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e


@router.post("/datasets/{name}/replace", summary="Hand a purpose over to a new dataset")
def replace_dataset(name: str, payload: ReplaceIn, session: Session = Depends(get_db),
                    principal: Principal = RequirePublisher) -> dict:
    try:
        return governance.replace_dataset(
            session, outgoing=name, incoming=payload.incoming,
            acknowledge=payload.acknowledge,
        )
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_409_CONFLICT) from e


# ================================================ harmonisation and assistants


class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=400)


class AcceptIn(BaseModel):
    accepted: dict[str, str] = Field(
        default_factory=dict,
        description="{source column: governed field} — only the ones you agree with.",
    )


@router.get("/datasets/{name}/harmonise", summary="Match columns to the governed dictionary")
def harmonise(name: str, session: Session = Depends(get_db)) -> dict:
    """Propose a governed field for every source column, with the reason.

    Nothing is applied. Each proposal carries the evidence behind it so a steward
    can check it rather than trust a score.
    """
    try:
        return harmonisation.propose(session, name)
    except DataBuilderError as e:
        raise _fail(e, status.HTTP_404_NOT_FOUND) from e


@router.post("/datasets/{name}/harmonise/accept", summary="Apply the proposals you agree with")
def accept_harmonisation(name: str, payload: AcceptIn, session: Session = Depends(get_db),
                         principal: Principal = RequireDataSteward) -> dict:
    try:
        return harmonisation.accept(session, name, payload.accepted)
    except DataBuilderError as e:
        raise _fail(e) from e


# ================================================================= the viewer


@router.get("/tree", summary="Every dataset, by domain, family and period")
def dataset_tree() -> dict:
    """The shape a person navigates in, rather than the flat list the engine reads."""
    return db_service.dataset_tree()


@router.get("/datasets/{name}/rows", summary="Read a page of a dataset")
def dataset_rows(
    name: str,
    period: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    sort: str | None = None,
    descending: bool = False,
    fields: str | None = Query(default=None,
                               description="Comma-separated governed field names."),
    principal: Principal = RequireDataSteward,
) -> dict:
    """One page of governed rows, with the schema that explains them.

    Every field named here is checked against the governed dictionary before it
    is read, and the sort column must be one of them — a column name can never
    become a query.
    """
    try:
        return db_service.browse_dataset(
            name,
            period=period,
            offset=offset,
            limit=limit,
            sort=sort,
            descending=descending,
            fields=[f.strip() for f in fields.split(",")] if fields else None,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"error": "invalid_request", "message": str(e)},
        ) from e


@router.post("/assistant", summary="Ask about the data model")
def data_assistant(payload: AskIn) -> dict:
    """Answer a question about CreditProbe's governed metadata.

    Reads domain, dataset, field and analysis definitions. It has no access to
    portfolio data, states no credit figures, and changes nothing.
    """
    return assistant.ask(payload.question, scope="data").to_dict()
