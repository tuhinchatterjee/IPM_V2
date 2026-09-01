# Export acceptance

§57 of the P1/P2 export brief asks for the download journey to be verified on a
running browser rather than reasoned about. These two scripts are that
verification, kept in the repository so the next person can re-run it rather
than take a report's word for it.

    export_browser_acceptance.py   drives Chromium: asks the mandatory question,
                                   checks both buttons and their placement,
                                   downloads both workbooks, reads the on-screen
                                   figures, and records everything under
                                   /tmp/accept.

    verify_workbooks.py            opens what was downloaded: sheet order,
                                   every required section, the SQL, the figures
                                   against the screen, the rating-wise total
                                   against the source profile, and a scan for
                                   anything that should never leave the product.

## Running them

Start the stack first — the backend on 8000 and the frontend on 3000 — then:

    python3 scripts/acceptance/export_browser_acceptance.py
    python  scripts/acceptance/verify_workbooks.py

Both exit non-zero on a failure, so they can be chained in a shell or a job.

## Units, and why the comparison scales

The interface renders exposure as `usd bn` and shows `22.4`; the workbook
carries the governed unit `USD mn` and the figure `22,373.572`. Both are
labelled and both are right — the screen is for reading and the workbook is the
record — so `verify_workbooks.py` puts them in the same unit before comparing
rather than pretending the rounded figure is the exact one.

## What they need

Chromium (already installed at `/opt/pw-browsers`), Playwright, and openpyxl.
Nothing is written into the repository: the downloads land in `/tmp/accept` and
the screenshots in `/tmp/shots`, both ignored.
