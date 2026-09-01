"""
Orchestration — the only place in the backend where a language model is used.

The boundary this package guards (docs/ARCHITECTURE.md §5):

    question -> PLANNER -> AnalysisPlan -> VALIDATOR -> EXECUTOR -> engine
                 (LLM)     (structured)     (strict)   (deterministic)

    narrative <- INTERPRETER <-------------- structured results

The planner and the interpreter are the only steps where judgement is exercised.
Between them sits the validator, which rejects any plan naming an unregistered
analysis or supplying a parameter that violates its contract — so the model can
choose *what* to compute but never *how*, and never computes anything itself.

    schema.py        the AnalysisPlan contract: registered ids and parameters,
                     and nothing else. No SQL field, no expression field.
    vocabulary.py    the periods, dimensions and values that genuinely exist,
                     read from the governed layer rather than assumed.
    validator.py     strict rejection of anything unregistered or non-conforming.
    planner.py       question -> AnalysisPlan. Deterministic when no model key is
                     configured; a language model when one is.
    executor.py      walks the plan, calls the engine, stitches the step traces
                     into one Analytical Reasoning Map.
    interpreter.py   structured results -> findings. Selects, orders and formats
                     figures the engine returned; performs no arithmetic.
    modification.py  a plain-English change -> one supported operation -> a new
                     plan -> a preview -> a new trace version.
    store.py         reading and writing investigation versions. Insert only:
                     a modification never overwrites what came before.

DEMO_MODE
---------
With no `ANTHROPIC_API_KEY` configured, the *planner* is deterministic. The
engine, the data and the results are not: every figure still comes from
executing real registered analyses against the published data.
"""
