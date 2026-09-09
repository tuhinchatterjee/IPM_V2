"""
Turning a Document into files. Playbook §11.

The local, deterministic rendering path. It exists for three jobs that the
provider's document Skills cannot do:

* **Seeding.** `backend/demo/seed.py` states the rule the whole repository
  follows — a demonstration makes no provider call, because pre-answering the
  questions a presenter is about to ask live is exactly what §26 forbids. The
  three seeded workspaces still need real Word, PDF and PowerPoint files, so
  they are rendered here.
* **No provider configured.** The seeded history and its files stay browseable,
  and a deployment without a key can still see what Playbook produces.
* **Validation fallback.** A Skill output that fails parse-back does not become
  a "ready" artifact. The local render is the known-good alternative, and the
  file records which route actually produced it.

One palette, shared with `backend/reporting/writers.py`, so a Playbook report
and a committee pack from the same product look like the same product.
"""

from __future__ import annotations

from backend.playbook.render import docx_writer, pdf_writer, pptx_writer, xlsx_writer

#: CreditProbe's document palette, as hex. `backend/reporting/writers.py` holds
#: the same values as reportlab colours; kept as strings here because
#: python-docx and python-pptx each want their own type.
NAVY = "0b2436"
TEAL = "16b8a6"
INK = "16232f"
MUTED = "6c7a8c"
BORDER = "e3e8ef"
ROW_ALT = "f8fafc"

WRITERS = {
    "docx": docx_writer.write,
    "pdf": pdf_writer.write,
    "pptx": pptx_writer.write,
    "xlsx": xlsx_writer.write,
}

__all__ = ["BORDER", "INK", "MUTED", "NAVY", "ROW_ALT", "TEAL", "WRITERS", "render"]


def render(document, fmt: str) -> bytes:
    """Render one document into one format. Raises `UnsupportedFormat`."""
    from backend.playbook import capabilities

    cap = capabilities.require(fmt)
    return WRITERS[cap.format](document)
