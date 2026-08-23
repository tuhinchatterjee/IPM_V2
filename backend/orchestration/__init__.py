"""
Orchestration — the only place in the backend where a language model is used.

The boundary this package guards (docs/ARCHITECTURE.md §5):

    question -> PLANNER -> AnalysisPlan -> VALIDATOR -> EXECUTOR -> engine
                 (LLM)     (structured)     (strict)   (deterministic)

    narrative <- INTERPRETER <-------------- structured results

The planner and the interpreter are the only LLM steps. Between them sits the
validator, which rejects any plan naming an unregistered analysis or supplying a
parameter that violates its contract — so the model can choose *what* to compute
but never *how*, and never computes anything itself.

Phase 3 adds:
  schema.py       the AnalysisPlan contract
  validator.py    strict rejection of anything unregistered or non-conforming
  executor.py     walks the plan, calls the engine, emits trace nodes
  planner.py      question -> AnalysisPlan
  interpreter.py  structured results -> narrative
"""
