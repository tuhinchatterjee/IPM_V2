# Scorecard Validation Runbook

How to build, register, validate, report and check the module.

---

## 1. Build the universe

```bash
.venv/bin/python scripts/build_retail_scorecards.py --register
```

~30 seconds. Generates both scorecards over 31 months (589,000 rows), fits the
frozen binning and three models per scorecard on the out-of-time development
sample, scores every month, writes the Parquet lake, registers the governed
catalogue, and records the six models and fifteen demonstration limits in the
registry.

Options:

| Flag | Effect |
|---|---|
| `--application-only` / `--behavioral-only` | One side |
| `--months N` | First N months, for a fast smoke run |
| `--no-catalogue` | Skip catalogue registration |
| `--register` | Also record the model registry (needs a database) |

Deterministic — the same seed reproduces the same universe.

---

## 2. Migrations

```bash
.venv/bin/python -m alembic upgrade head     # head is 0028
.venv/bin/python -m alembic current
```

---

## 3. Run the module

```bash
.venv/bin/uvicorn backend.api.main:app --reload   # API
cd frontend && npm run dev                        # UI at /scorecard-validation
```

Twelve tabs plus Reports: cockpit, dashboard, discrimination, calibration,
stability, variables, models, diagnostics, trends, findings, governance, data,
reports.

---

## 4. Generate a report

Through the screen: **Reports → Generate validation report**, then either
download button.

Through the API:

```bash
curl -X POST localhost:8000/api/v1/scorecard/reports/APPLICATION \
     -H 'Content-Type: application/json' -d '{}'
curl -OJ 'localhost:8000/api/v1/scorecard/reports/APPLICATION/download?fmt=docx'
curl -OJ 'localhost:8000/api/v1/scorecard/reports/APPLICATION/download?fmt=xlsx'
```

Requires `SCORECARD_REPORT_GENERATE` (Administrator or Data Steward).

---

## 5. The checks

```bash
# The 24 zero-tolerance checks, against the real engine
.venv/bin/python -c "from backend.scorecard import critical; \
  import json; print(json.dumps(critical.run().to_dict(), indent=1))"

# Layered evaluation over the 500-case development corpus
.venv/bin/python -c "from backend.scorecard import evaluation as e; \
  from intelligence_factory.teaching import scorecard as s; \
  import json; print(json.dumps(e.run(s.cases()).to_dict()['by_dimension'], indent=1))"

# Holdout isolation
.venv/bin/python -c "from backend.scorecard import holdout as h; \
  from intelligence_factory.teaching import scorecard as s; \
  h.isolated(s.cases()); print('isolated')"

# Portability audit
.venv/bin/python -c "from backend.scorecard import portable as p; \
  print(p.audit() or 'clean')"
```

---

## 6. Tests

```bash
.venv/bin/python -m pytest tests/scorecard -q      # the module
.venv/bin/python -m pytest -q                      # everything
cd frontend && npm test                            # frontend
```

---

## 7. Gates

```bash
.venv/bin/python -m ruff check backend/ tests/ scripts/ alembic/ intelligence_factory/
.venv/bin/python scripts/check_decimals.py
.venv/bin/python scripts/feature_matrix.py --write
cd frontend && npx tsc --noEmit && npx eslint .
```

---

## 8. If PostgreSQL is not running

```bash
pg_isready || pg_ctlcluster 16 main start
```

Connection-refused failures in the API tests look exactly like a regression
and are not one.

---

## 9. Demonstrating the maturity guard

The six open months are what make §7 visible:

```bash
.venv/bin/python -c "
from backend.scorecard import synthetic as s
print([m for m in s.APPLICATION_MONTHS if not s.matured(m)])"
# ['2025-02', '2025-03', '2025-04', '2025-05', '2025-06', '2025-07']
```

Open one on the dashboard: discrimination and calibration state when the
window closes; stability, variables and implementation still report. Generate
a report for the same month and section 8.3 carries the reason instead of a
table.

---

## 10. Windows and Docker

See `WINDOWS_LOCAL_VERIFICATION.md`. Docker build and start, and any live AI
verification, are not run in the cloud sandbox and are not claimed to pass
there.
