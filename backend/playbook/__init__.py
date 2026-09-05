"""Playbook — the committee pack intelligence system.

A committee pack is not a document. It is a governed record of what a forum was
told, which numbers it was told, where those numbers came from, what it decided
and what somebody then had to do. This package is that lifecycle:

    committee -> schedule -> data readiness -> generation -> analysis ->
    commentary -> review -> approval -> presentation -> decisions ->
    actions -> planner follow-up -> the next pack

Module map
----------
    access      who may read and change what; the single door
    service     committees, packs, sections, blocks — the CRUD with governance
    readiness   whether a pack can go to committee, and precisely why not
    materiality deterministic rules that decide what is worth saying
    snapshots   freezing a governed figure into a pack, reproducibly
    generation  building a pack from a template and the data
    narrative   AI commentary, bounded by the snapshots it is given
    compare     what changed since the previous approved pack
    monitor     the schedule sweep that chases people
    agent       background jobs, registered on the existing worker
    actions     the bridge to the Project Planner
    export      PDF, DOCX and the evidence workbook
    import_     reading somebody's existing pack into a draft
    demo        three realistic committees, built and refreshed by arithmetic

What this package does NOT own: identity, notifications, comments, exports
records, tasks, metric formulas, chart rendering or the job queue. Every one of
those is an existing CreditProbe service and Playbook calls it.
"""

from __future__ import annotations
