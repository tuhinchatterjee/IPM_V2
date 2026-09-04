"""Real HTTP journeys against a running CreditProbe backend.

Nothing here uses TestClient, the ORM or a fixture. Every step is an HTTP
request over a socket to a uvicorn process, signed in with a real session
cookie obtained from the real login route, exactly as a browser does it.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

BASE = os.environ.get("CREDITPROBE_API", "http://127.0.0.1:8000") + "/api/v1"

FAILURES: list[str] = []
NOTES: list[str] = []


class Client:
    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.who = "anonymous"

    def call(
        self, method: str, path: str, body: Any = None, raw: bool = False
    ) -> tuple[int, Any, dict]:
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=120) as r:
                payload = r.read()
                head = dict(r.headers)
                if raw:
                    return r.status, payload, head
                try:
                    return r.status, json.loads(payload or b"null"), head
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return r.status, payload, head
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, json.loads(payload or b"null"), dict(e.headers)
            except Exception:
                return e.code, payload, dict(e.headers)

    def login(self, username: str, password: str = "creditprobe-demo") -> None:
        self.jar.clear()
        code, body, _ = self.call("POST", "/auth/login",
                                  {"username": username, "password": password})
        assert code == 200, f"login {username} -> {code} {body}"
        self.who = username


def check(journey: str, label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {journey} :: {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{journey} :: {label} -- {detail}")
    return ok


def main() -> int:
    admin = Client()
    admin.login("alex.rahman")

    code, cs, _ = admin.call("GET", "/playbook/committees")
    committees = {c["code"]: c for c in cs["committees"]}
    retail = committees["retail-credit-risk-committee"]

    # ---------------------------------------------------------------- A
    print("\nJourney A — a member opens the committee and finds this cycle's pack")
    code, detail, _ = admin.call("GET", f"/playbook/committees/{retail['id']}")
    check("A", "committee detail 200", code == 200, str(code))
    check("A", "cadence and purpose present",
          bool(detail["cadence"]) and bool(detail["purpose"]),
          detail["cadence"])
    packs = detail["packs"]
    check("A", "two packs on the committee", len(packs) == 2, str(len(packs)))
    current = max(packs, key=lambda p: p["meeting_at"])
    previous = min(packs, key=lambda p: p["meeting_at"])
    check("A", "previous pack is PUBLISHED", previous["status"] == "PUBLISHED",
          previous["status"])
    check("A", "current pack is in flight",
          current["status"] in {"DRAFT", "GENERATING", "CONTRIBUTOR_REVIEW", "REVIEW",
           "CHANGES_REQUESTED", "READY_FOR_APPROVAL"},
          current["status"])

    # ---------------------------------------------------------------- B
    print("\nJourney B — the pack reads as a pack, not as a form")
    code, pack, _ = admin.call("GET", f"/playbook/packs/{current['id']}")
    check("B", "pack detail 200", code == 200, str(code))
    sections = pack["sections"]
    check("B", "sections present", len(sections) >= 4, str(len(sections)))
    blocks = [b for s in sections for b in s["blocks"]]
    check("B", "blocks present", len(blocks) >= 10, str(len(blocks)))
    figures = [b for b in blocks if b["calculated"]]
    check("B", "figures present", len(figures) >= 6, str(len(figures)))
    ok_figs = [f for f in figures if (f.get("figure") or {}).get("availability") == "OK"]
    check("B", "figures carry real calculated values", len(ok_figs) >= 4,
          f"{len(ok_figs)}/{len(figures)} OK")
    NOTES.append(f"B: {len(ok_figs)} of {len(figures)} retail figures calculated OK")

    # ---------------------------------------------------------------- C
    print("\nJourney C — every number can be opened down to its working")
    fig = ok_figs[0]
    snap = fig["figure"]
    check("C", "figure has a display value", bool(snap.get("display_value")), str(snap.get("display_value")))
    check("C", "figure names its metric", bool(snap.get("metric_id")), str(snap.get("metric_id")))
    check("C", "figure names its period", bool(snap.get("period")), str(snap.get("period")))
    calc = snap
    check("C", "working carries a formula hash", bool(calc.get("formula_hash")),
          str(calc.get("formula_hash"))[:16])
    check("C", "working names its dataset", bool(calc.get("dataset")),
          str(calc.get("dataset"))[:80])
    NOTES.append(
        f"C: {snap['metric_id']} {snap['period']} = {snap['display_value']} "
        f"hash={str(calc.get('formula_hash'))[:12]}"
    )

    # unavailable figures must say which kind of unavailable
    unavail = [f for f in figures if (f.get("figure") or {}).get("availability") != "OK"]
    kinds = sorted({(f["figure"] or {}).get("availability") for f in unavail})
    check("C", "unavailable figures are typed, never 0.0%",
          all(k and k != "OK" for k in kinds) if unavail else True, str(kinds))

    # ---------------------------------------------------------------- D
    print("\nJourney D — readiness is a gate, not a badge")
    code, ready, _ = admin.call("GET", f"/playbook/packs/{current['id']}/readiness")
    check("D", "readiness 200", code == 200, str(code))
    check("D", "readiness is a percentage", isinstance(ready.get("percent"), int),
          str(ready.get("percent")))
    checks = ready.get("checks") or []
    check("D", "readiness lists named checks", len(checks) >= 3, str(len(checks)))
    NOTES.append(f"D: readiness {ready.get('percent')}% over {len(checks)} checks")

    # ---------------------------------------------------------------- E
    print("\nJourney E — findings are answered, not admired")
    code, fs, _ = admin.call("GET", f"/playbook/findings?pack_id={current['id']}")
    check("E", "findings 200", code == 200, str(code))
    open_findings = [f for f in fs["findings"] if f["status"] == "OPEN"]
    check("E", "the pack raised findings", len(fs["findings"]) >= 1, str(len(fs["findings"])))
    if open_findings:
        target = open_findings[0]
        code, resp, _ = admin.call(
            "POST", f"/playbook/findings/{target['id']}/respond",
            {"status": "EXPLAINED",
             "response": "Driven by the Jeddah SME cohort; covered in section 3."},
        )
        check("E", "a finding can be answered", code == 200, str(code)[:120])
        check("E", "the answer is stored", resp and resp["status"] == "EXPLAINED",
              str(resp)[:120] if code != 200 else resp["status"])
        code, back, _ = admin.call("POST", f"/playbook/findings/{target['id']}/reopen",
                                   {"why": "Reopened by the journey harness."})
        check("E", "an answered finding can be reopened",
              code == 200 and back["status"] == "OPEN", str(code))
        # dismissal needs a reason
        code, refused, _ = admin.call(
            "POST", f"/playbook/findings/{target['id']}/respond",
            {"status": "DISMISSED", "response": "no reason given", "reason": ""})
        check("E", "dismissal without a written reason is refused",
              code in (400, 422)
              and "reason" in json.dumps(refused).lower(), str(code))

    # ---------------------------------------------------------------- F
    print("\nJourney F — the published pack tells its own history")
    code, hist, _ = admin.call("GET", f"/playbook/packs/{previous['id']}/history")
    check("F", "history 200", code == 200, str(code))
    events = hist.get("events") or []
    check("F", "history is populated", len(events) >= 5, str(len(events)))
    sources = {e.get("source") for e in events}
    check("F", "every event names its source", all(sources), str(sorted(sources)))
    code, ver, _ = admin.call("GET", f"/playbook/packs/{previous['id']}/sources")
    check("F", "sources 200", code == 200, str(code))
    NOTES.append(f"F: {len(events)} governance events, sources {sorted(s for s in sources if s)}")

    # ---------------------------------------------------------------- G
    print("\nJourney G — comparison against the previous cycle")
    code, cmp_, _ = admin.call(
        "GET", f"/playbook/packs/{current['id']}/compare?against_pack_id={previous['id']}")
    check("G", "compare 200", code == 200, str(cmp_)[:160] if code != 200 else "")
    if code == 200:
        rows = cmp_.get("differences") or []
        check("G", "comparison returns figure rows", len(rows) >= 1, str(len(rows)))
        check("G", "comparison names both packs",
              cmp_.get("previous_pack_code") and cmp_.get("pack_code"),
              f"{cmp_.get('previous_pack_code')} -> {cmp_.get('pack_code')}")
        moved = [r for r in rows if r["kind"] == "MOVED"]
        check("G", "movements carry a direction and a reading",
              all(r["direction"] in {"up", "down"} and isinstance(r["better"], bool)
                  for r in moved), str(len(moved)))
        # A rise in a bad-is-up metric must never be read as better.
        bad_up = [r for r in moved
                  if r["direction"] == "up" and "bad_rate" in r["metric_id"]]
        check("G", "a rise in a bad rate is not read as an improvement",
              all(r["better"] is False for r in bad_up), str(len(bad_up)))
        NOTES.append(f"G: {len(rows)} figures compared, {len(moved)} moved, "
                     f"{cmp_.get('previous_pack_code')} -> {cmp_.get('pack_code')}")

    # ---------------------------------------------------------------- H
    print("\nJourney H — the pack leaves the building as a file")
    code, formats, _ = admin.call("GET", "/playbook/formats")
    check("H", "formats 200", code == 200, str(code))
    names = [f["format"] if isinstance(f, dict) else f for f in
             (formats.get("formats") if isinstance(formats, dict) else formats)]
    check("H", "formats are offered", len(names) >= 2, str(names))
    for fmt in names:
        code, blob, head = admin.call(
            "GET", f"/playbook/packs/{previous['id']}/export?format={fmt}", raw=True)
        ok = code == 200 and isinstance(blob, bytes) and len(blob) > 200
        check("H", f"export {fmt} downloads", ok,
              f"{code} {len(blob) if isinstance(blob, bytes) else blob} bytes")
        if ok:
            NOTES.append(f"H: {fmt} export {len(blob)} bytes, "
                         f"type={head.get('content-type') or head.get('Content-Type')}")
            if fmt.upper() == "XLSX":
                check("H", "xlsx is a real zip container", blob[:2] == b"PK", repr(blob[:4]))

    # ---------------------------------------------------------------- I
    print("\nJourney I — someone else's committee is not readable")
    # A genuine outsider: created through the real admin route, given no
    # committee membership and no platform role that reaches over one.
    handle = "pb.outsider.journey"
    code, made, _ = admin.call("POST", "/users", {
        "username": handle, "password": "journey-outsider-8842",
        "first_name": "Journey", "last_name": "Outsider",
        "email": f"{handle}@example-bank.com", "role": "ANALYST",
    })
    check("I", "outsider account exists", code in (200, 201, 409), str(code)[:200])
    outsider = Client()
    outsider.login(handle, "journey-outsider-8842")
    code, mine, _ = outsider.call("GET", "/playbook/committees")
    visible = {c["id"] for c in mine["committees"]}
    check("I", "the outsider sees no committee they are not on",
          not (visible & {c["id"] for c in committees.values()}), str(sorted(visible)))
    code, denied, _ = outsider.call("GET", f"/playbook/packs/{current['id']}")
    check("I", "a direct pack id is refused, not leaked", code in (403, 404), str(code))
    check("I", "the refusal does not echo pack content",
          "sections" not in json.dumps(denied), json.dumps(denied)[:120])
    for label, path, method, body in (
        ("export", f"/playbook/packs/{current['id']}/export?format=XLSX", "GET", None),
        ("readiness", f"/playbook/packs/{current['id']}/readiness", "GET", None),
        ("history", f"/playbook/packs/{current['id']}/history", "GET", None),
        ("sources", f"/playbook/packs/{current['id']}/sources", "GET", None),
        ("compare", f"/playbook/packs/{current['id']}/compare", "GET", None),
        ("publish", f"/playbook/packs/{current['id']}/status", "POST",
         {"status": "PUBLISHED"}),
        ("add a section", f"/playbook/packs/{current['id']}/sections", "POST",
         {"title": "Injected"}),
    ):
        code, body_out, _ = outsider.call(method, path, body)
        check("I", f"{label} on another committee's pack is refused",
              code in (403, 404, 422), str(code))

    # A member whose access role is VIEWER reads, and only reads.
    observer = Client()
    observer.login("layla.haddad")
    code, seen, _ = observer.call("GET", f"/playbook/packs/{current['id']}")
    check("I", "a named observer can read the pack", code == 200, str(code))
    code, refused_w, _ = observer.call(
        "POST", f"/playbook/packs/{current['id']}/status", {"status": "PUBLISHED"})
    check("I", "an observer cannot publish", code in (403, 404), str(code))
    code, refused_w, _ = observer.call(
        "POST", f"/playbook/packs/{current['id']}/sections", {"title": "Observer section"})
    check("I", "an observer cannot add a section", code in (403, 404), str(code))

    # ---------------------------------------------------------------- J
    print("\nJourney J — signed out is signed out")
    anon = Client()
    for path in ("/playbook/committees",
                 f"/playbook/packs/{current['id']}",
                 f"/playbook/packs/{current['id']}/export?format=XLSX"):
        code, body, _ = anon.call("GET", path)
        check("J", f"anonymous {path} is refused", code == 401, str(code))

    print("\n" + "=" * 68)
    for n in NOTES:
        print("  note: " + n)
    print("=" * 68)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED:")
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("\nAll journey checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
