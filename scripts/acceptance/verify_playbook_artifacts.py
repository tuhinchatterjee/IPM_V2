"""
Open every Playbook artifact and check it. Playbook §11, §20, PB-041.

Two passes over every generated file in the demonstration.

**Programmatic.** Reopen it with the same parsers Playbook uses on user uploads
and check it against the document it was rendered from: the sections that should
be there, the tables that should be there, and — the part that matters — no
figure that is in no source. This is `backend/playbook/validate.py` run against
what is actually on disk rather than against what was in memory when it was
written.

**Visual.** Rasterise every PDF page and inspect it for the failures a parser
cannot see: a blank page, a page that is nearly all ink, content running past
the margins, or a page whose text density says something has collapsed. The
images are written out so a human can look at the ones this flags.

    .venv/bin/python scripts/acceptance/verify_playbook_artifacts.py

Exit 0 if everything held, 1 if anything did not, 2 if it could not run.
`pymupdf` is a development dependency used only here; the application does not
rasterise anything.
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

RENDERS = REPO / "docs" / "playbook" / "artifact-pages"
EVIDENCE = REPO / "docs" / "playbook" / "artifact_verification.json"

#: A page with almost no ink is a blank page somebody will print.
MIN_INK_RATIO = 0.0008
#: A page that is nearly all ink has collapsed — overlapping text, a black box.
MAX_INK_RATIO = 0.60
#: Content must stay inside the margin the writer set.
MARGIN_POINTS = 12.0

ok: list[str] = []
bad: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    (ok if condition else bad).append(
        f"{name}{(' — ' + detail) if detail else ''}")
    print(("  PASS  " if condition else "  FAIL  ") + name
          + (f"  {detail}" if detail else ""), flush=True)
    return bool(condition)


def _ink_ratio(pixmap) -> float:
    """Roughly how much of the page is not the paper colour."""
    samples = pixmap.samples
    stride = max(1, len(samples) // 20000)  # sample rather than scan every byte
    dark = total = 0
    for i in range(0, len(samples), stride):
        total += 1
        if samples[i] < 200:
            dark += 1
    return dark / max(1, total)


def inspect_pdf(content: bytes, label: str) -> None:
    import pymupdf

    RENDERS.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(stream=content, filetype="pdf")
    check(f"{label}: the PDF has pages", doc.page_count > 0,
          f"{doc.page_count} page(s)")

    for index, page in enumerate(doc, start=1):
        pixmap = page.get_pixmap(dpi=90)
        image = RENDERS / f"{label.replace('/', '-')}-p{index}.png"
        pixmap.save(str(image))

        ratio = _ink_ratio(pixmap)
        check(f"{label} p{index}: is not blank", ratio > MIN_INK_RATIO,
              f"ink {ratio:.4f}")
        check(f"{label} p{index}: has not collapsed into a block",
              ratio < MAX_INK_RATIO, f"ink {ratio:.4f}")

        rect = page.rect
        overflowing = [
            b for b in page.get_text("blocks")
            if b[0] < -MARGIN_POINTS or b[1] < -MARGIN_POINTS
            or b[2] > rect.width + MARGIN_POINTS
            or b[3] > rect.height + MARGIN_POINTS
        ]
        check(f"{label} p{index}: nothing runs off the page", not overflowing,
              f"{len(overflowing)} block(s) outside")

        fonts = page.get_fonts()
        check(f"{label} p{index}: text is drawn with a real font",
              bool(fonts) or not page.get_text().strip(),
              f"{len(fonts)} font(s)")
    doc.close()


def main() -> int:
    from backend.config import settings

    if not settings.has_database:
        print("CANNOT RUN: no database configured, so there are no artifacts.")
        return 2
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        print("CANNOT RUN: pymupdf is not installed, so PDF pages cannot be "
              "rendered. Visual inspection is NOT RUN, which is not a pass.")
        return 2

    from backend.agentic.principals import tenant_of
    from backend.db.engine import get_session
    from backend.playbook import document as D
    from backend.playbook import repository as repo
    from backend.playbook import seed, store, validate

    print("Playbook artifact verification")
    print("=" * 72)
    scope = repo.Scope(tenant=tenant_of(None))
    inspected = 0

    with get_session() as session:
        state = seed.status(session, scope)
        if not state["workspaces_present"]:
            print("CANNOT RUN: no seeded workspaces. Run "
                  "scripts/bootstrap_demo.py --step playbook")
            return 2

        from sqlalchemy import select

        from backend.models.playbook import PlaybookWorkspace

        for title in state["workspaces_present"]:
            ws = session.execute(select(PlaybookWorkspace).where(
                PlaybookWorkspace.tenant == scope.tenant,
                PlaybookWorkspace.title == title)).scalars().first()
            print(f"\n-- {title} " + "-" * max(0, 50 - len(title)))

            for artifact in repo.artifacts(session, ws.id):
                for version in repo.versions(session, artifact.id):
                    doc = D.Document.from_dict(version.content)
                    for row in repo.files(session, version.id):
                        label = f"{artifact.kind} v{version.version} {row.format}"
                        content = store.read(row.bytes_path)

                        check(f"{label}: the stored bytes are the ones recorded",
                              store.sha256(content) == row.sha256)
                        result = validate.validate(content, row.format, doc)
                        check(f"{label}: reopens and matches its document",
                              result.ok, "; ".join(result.issues))
                        if row.format == "pdf":
                            inspect_pdf(content, label)
                        inspected += 1

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps({
        "files_inspected": inspected,
        "passed": ok, "failed": bad,
        "rendered_pages": sorted(p.name for p in RENDERS.glob("*.png")),
    }, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 72)
    print(f"{inspected} file(s) inspected. {len(ok)} checks passed, "
          f"{len(bad)} failed. Evidence: {EVIDENCE.relative_to(REPO)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
