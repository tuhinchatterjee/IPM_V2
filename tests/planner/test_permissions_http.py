"""Who may do what, asked of the running application over HTTP.

Every assertion here is a status code from a real request. That is deliberate
and it is the whole point of the file: a permission proved by calling a
service function with a hand-built principal proves the service checks, and
says nothing about whether the route reached it. The bugs this catches — a
route that forgot its dependency, a PATCH that resolves the object before
resolving access, a 404 that leaks existence by being a 403 — only exist at
the HTTP boundary.

CreditProbe is single-tenant: there is no organisation table, so the spec's
"tenant crossover" is membership crossover here. Mallory is the crossover
case, and she is a legitimate signed-in user, which is what makes it real.
"""

from __future__ import annotations

from tests.planner.conftest import PREFIX, headers


class TestReading:
    def test_a_participant_reads_the_project(self, client, cast, project):
        for who in ("alice", "bob", "carol"):
            got = client.get(f"{PREFIX}/projects/{project['id']}",
                             headers=headers(cast[who]))
            assert got.status_code == 200, f"{who}: {got.text}"
            assert got.json()["project"]["id"] == project["id"]

    def test_an_outsider_is_told_it_does_not_exist(self, client, cast,
                                                   project):
        """404, not 403.

        403 confirms the project exists, which turns /projects/{id} into a
        way to enumerate the estate: walk the integers, count the 403s, and
        you know how many projects the bank is running and which ids are
        live. The refusal must be indistinguishable from an id that names
        nothing.
        """
        got = client.get(f"{PREFIX}/projects/{project['id']}",
                         headers=headers(cast["mallory"]))
        assert got.status_code == 404, got.text

        absent = client.get(f"{PREFIX}/projects/98765432",
                            headers=headers(cast["mallory"]))
        assert absent.status_code == 404
        assert got.json()["detail"]["error"] == absent.json()["detail"]["error"]

    def test_the_portfolio_only_lists_your_own(self, client, cast, project):
        mine = client.get(f"{PREFIX}/projects", headers=headers(cast["bob"]))
        assert mine.status_code == 200
        assert project["id"] in [p["id"] for p in mine.json()["projects"]]

        theirs = client.get(f"{PREFIX}/projects",
                            headers=headers(cast["mallory"]))
        assert theirs.status_code == 200
        assert project["id"] not in [p["id"] for p in theirs.json()["projects"]]

    def test_an_outsider_cannot_read_the_activity_log(self, client, cast,
                                                      project):
        got = client.get(f"{PREFIX}/projects/{project['id']}/activity",
                         headers=headers(cast["mallory"]))
        assert got.status_code == 404


class TestWriting:
    def test_a_contributor_updates_their_own_task(self, client, cast,
                                                  project):
        done = client.patch(
            f"{PREFIX}/tasks/{project['bob_task']}",
            headers=headers(cast["bob"]),
            json={"percent_complete": 40,
                  "narrative": "Extract written, sampling next."})
        assert done.status_code == 200, done.text
        assert done.json()["task"]["percent_complete"] == 40

    def test_a_contributor_cannot_update_somebody_elses_task(self, client,
                                                             cast, project):
        refused = client.patch(
            f"{PREFIX}/tasks/{project['alice_task']}",
            headers=headers(cast["bob"]),
            json={"percent_complete": 90})
        assert refused.status_code == 403, refused.text

    def test_a_contributor_cannot_move_their_own_due_date(self, client, cast,
                                                          project):
        """Reporting progress and changing the commitment are different acts.

        This is the permission the whole product rests on: if the person
        doing the work can move the date they are measured against, nothing
        is ever late and the portfolio view is decoration.
        """
        refused = client.patch(
            f"{PREFIX}/tasks/{project['bob_task']}",
            headers=headers(cast["bob"]), json={"due_date": "2026-11-30"})
        assert refused.status_code == 403, refused.text

    def test_a_viewer_cannot_write(self, client, cast, project):
        refused = client.patch(
            f"{PREFIX}/tasks/{project['bob_task']}",
            headers=headers(cast["carol"], role="VIEWER"),
            json={"percent_complete": 100})
        assert refused.status_code == 403, refused.text

    def test_a_viewer_cannot_post_an_update_either(self, client, cast,
                                                   project):
        """VIEWER means viewer, with no exception for prose.

        There is a real argument the other way — a sponsor given read access
        who wants to write "I need this by the 12th" is a normal thing to
        want. It is refused deliberately: an update row is part of the
        project's permanent history, it is what "what changed since Friday?"
        reads, and one carve-out in "a viewer writes nothing" is the sentence
        a security review can no longer state plainly. A sponsor who needs to
        speak is given CONTRIBUTOR, which an owner can do in one click.
        """
        said = client.post(
            f"{PREFIX}/projects/{project['id']}/updates",
            headers=headers(cast["carol"], role="VIEWER"),
            json={"narrative": "Reviewed; no concerns from my side."})
        assert said.status_code == 403, said.text

    def test_an_outsider_cannot_write_anything(self, client, cast, project):
        attempts = [
            client.patch(f"{PREFIX}/projects/{project['id']}",
                         headers=headers(cast["mallory"]),
                         json={"name": "Mine now"}),
            client.patch(f"{PREFIX}/tasks/{project['bob_task']}",
                         headers=headers(cast["mallory"]),
                         json={"percent_complete": 100}),
            client.post(f"{PREFIX}/projects/{project['id']}/tasks",
                        headers=headers(cast["mallory"]),
                        json={"code": "T-EVIL", "title": "Injected"}),
            client.post(f"{PREFIX}/projects/{project['id']}/participants",
                        headers=headers(cast["mallory"]),
                        json={"user_id": cast["mallory"], "access": "OWNER"}),
            client.post(f"{PREFIX}/projects/{project['id']}/updates",
                        headers=headers(cast["mallory"]),
                        json={"narrative": "hello"}),
            client.delete(f"{PREFIX}/tasks/{project['bob_task']}",
                          headers=headers(cast["mallory"])),
        ]
        assert [a.status_code for a in attempts] == [404] * 6, \
            [(a.request.url.path, a.status_code, a.text[:120])
             for a in attempts if a.status_code != 404]

    def test_a_contributor_cannot_promote_themselves(self, client, cast,
                                                     project):
        refused = client.post(
            f"{PREFIX}/projects/{project['id']}/participants",
            headers=headers(cast["bob"]),
            json={"user_id": cast["bob"], "access": "OWNER"})
        assert refused.status_code == 403, refused.text

    def test_the_project_still_belongs_to_alice(self, client, cast, project):
        """After every attempt above, read the truth back.

        Status codes prove the refusal was returned. This proves nothing got
        through anyway — the failure mode where a route refuses AND commits.
        """
        got = client.get(f"{PREFIX}/projects/{project['id']}",
                         headers=headers(cast["alice"]))
        detail = got.json()
        assert detail["project"]["name"] == "Permission fixture project"
        assert not any(t["code"] == "T-EVIL" for t in detail["tasks"])
        holders = {p["user"]["id"]: p["access"]
                   for p in detail["participants"] if p.get("user")}
        assert holders.get(cast["bob"]) == "CONTRIBUTOR"
        assert cast["mallory"] not in holders
