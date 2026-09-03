"""
PostgreSQL models for the application, governance and metadata layer.

PostgreSQL is the filing cabinet: everything the bank has decided, configured or
recorded. Large monthly analytical data does NOT live here — that is Parquet,
read through the Data Access Layer (docs/ARCHITECTURE.md §4.1).

  platform.py       projects, chats, analysis runs, trace graphs, engine and
                    data catalogue definitions, object-anchored workflow
  collaboration.py  message threads, messages, attachments, object shares,
                    review requests and the collaboration audit log
  planner.py        the Project Planner's system of record: delivery projects,
                    participants, workstreams, tasks, milestones,
                    dependencies, RAID, the append-only update history,
                    reminder fingerprints and workbook imports

The existing backend/db/models.py (dataset versions, users, AI usage) is retained
unchanged and shares the same declarative Base, so both sets of tables live in one
schema and one Alembic history.
"""
