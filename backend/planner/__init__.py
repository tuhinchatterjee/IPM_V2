"""The Project Planner.

Four responsibilities, deliberately kept apart:

  control.py   The deterministic project-control engine. Given a plan and its
               status, it decides what is overdue, what is due soon, what has
               gone stale, what a dependency threatens, how complete a project
               is and what colour it is. No model is called here and none ever
               should be: a RAG status a language model invented is a number
               nobody can defend to a steering committee.

  access.py    Who may read a project and who may change it. Every service
               call goes through it; nothing trusts the frontend.

  service.py   Validated, permission-aware mutations, each one writing its own
               history row and its own audit record.

  workbook.py  The Excel template, the import validator and the export.

  monitor.py   The scheduled sweep. Runs `control` over the open projects and
               turns its findings into reminders, exactly once each.

  agent.py     The tools the AI is allowed to call, and the structured briefs
               it summarises. It reads what `control` computed; it does not
               compute anything itself.
"""
