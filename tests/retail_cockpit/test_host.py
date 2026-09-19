"""The host side: who the engine thinks you are, and what it offers you.

No server and no engine. These are the two pieces of the boundary that are
pure functions of their inputs, and they are the two it would be easiest to
get quietly wrong: an identity that defaults to something, and a book list
that offers a book this installation does not have.
"""

from __future__ import annotations

import json

import pytest

from backend.retail_cockpit_host import identity


class _Headers(dict):
    """Case-insensitive, like a real request's."""

    def get(self, key, default=""):  # noqa: D102
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, **headers) -> None:
        self.headers = _Headers({k.lower(): v for k, v in headers.items()})


# ---- the boundary secret ----------------------------------------------

def test_neither_side_starts_without_a_secret(monkeypatch):
    """A default would be the same on every machine, so there is none."""
    monkeypatch.delenv(identity.SECRET_VAR, raising=False)
    with pytest.raises(identity.SecretMissing) as raised:
        identity.secret()
    assert identity.SECRET_VAR in str(raised.value)


def test_a_wrong_secret_is_not_a_principal(monkeypatch):
    monkeypatch.setenv(identity.SECRET_VAR, "the-real-one")
    resolve = identity.forwarded_resolver()
    request = _Request(**{
        identity.AUTH_HEADER: "not-the-real-one",
        identity.PRINCIPAL_HEADER: json.dumps({"id": "u1",
                                               "tenant": "demo-tenant"})})
    assert resolve(request) is None


def test_no_secret_at_all_is_not_a_principal(monkeypatch):
    """The engine must refuse, not fall back to trusting the header."""
    monkeypatch.delenv(identity.SECRET_VAR, raising=False)
    resolve = identity.forwarded_resolver()
    request = _Request(**{
        identity.PRINCIPAL_HEADER: json.dumps({"id": "u1"})})
    assert resolve(request) is None


def test_the_right_secret_carries_the_principal(monkeypatch):
    monkeypatch.setenv(identity.SECRET_VAR, "the-real-one")
    resolve = identity.forwarded_resolver()
    principal = {"id": "u1", "tenant": "demo-tenant", "name": "A Person"}
    request = _Request(**{identity.AUTH_HEADER: "the-real-one",
                          identity.PRINCIPAL_HEADER: json.dumps(principal)})
    assert resolve(request) == principal


@pytest.mark.parametrize("body", ["", "{", "[]", '{"tenant": "t"}', "null"])
def test_a_principal_without_an_id_is_not_a_principal(monkeypatch, body):
    monkeypatch.setenv(identity.SECRET_VAR, "the-real-one")
    resolve = identity.forwarded_resolver()
    request = _Request(**{identity.AUTH_HEADER: "the-real-one",
                          identity.PRINCIPAL_HEADER: body})
    assert resolve(request) is None


def test_the_tenant_is_the_deployment_s_not_the_caller_s(monkeypatch):
    """The retail app has no tenants; the engine scopes everything by one.

    So it is configured server-side and is the same for every principal. A
    caller that could choose it could read another deployment's rows.
    """
    monkeypatch.setenv(identity.TENANT_VAR, "demo-tenant")

    class _Account:
        id = 7
        greeting_name = "A Person"

    mapped = identity.principal_for(_Account(), "ANALYST")
    assert mapped["tenant"] == "demo-tenant"
    assert mapped["id"] == "7"
    assert mapped["role"] == "ANALYST"


# ---- what the deployment offers ---------------------------------------

def _books(*entries) -> bytes:
    return json.dumps({"domains": list(entries), "default": "retail"}).encode()


def test_a_book_this_deployment_does_not_publish_is_not_offered():
    from backend.api.routers import cockpit_v4_proxy as proxy

    class _Upstream:
        status_code = 200
        headers = {"content-type": "application/json", "content-length": "9"}

    payload, headers = proxy._published_books(
        "domains",
        _books({"domain_id": "corporate", "ready": False},
               {"domain_id": "retail", "ready": True}),
        _Upstream())
    assert [b["domain_id"] for b in json.loads(payload)["domains"]] == ["retail"]
    # The length changed, so the old one must not travel with it.
    assert "content-length" not in {k.lower() for k in headers}


def test_nothing_is_narrowed_when_nothing_needs_to_be():
    from backend.api.routers import cockpit_v4_proxy as proxy

    class _Upstream:
        status_code = 200
        headers = {"content-type": "application/json"}

    original = _books({"domain_id": "retail", "ready": True})
    payload, _ = proxy._published_books("domains", original, _Upstream())
    assert payload is original


def test_a_deployment_with_no_ready_book_says_so_rather_than_nothing():
    """Narrowing an empty list to an empty list would hide a real failure."""
    from backend.api.routers import cockpit_v4_proxy as proxy

    class _Upstream:
        status_code = 200
        headers = {"content-type": "application/json"}

    original = _books({"domain_id": "corporate", "ready": False},
                      {"domain_id": "retail", "ready": False})
    payload, _ = proxy._published_books("domains", original, _Upstream())
    assert payload is original
    assert len(json.loads(payload)["domains"]) == 2


@pytest.mark.parametrize("path", ["attention", "runs/r-1/events", "session"])
def test_only_the_book_list_is_touched(path):
    from backend.api.routers import cockpit_v4_proxy as proxy

    class _Upstream:
        status_code = 200
        headers = {"content-type": "application/json"}

    original = _books({"domain_id": "corporate", "ready": False},
                      {"domain_id": "retail", "ready": True})
    payload, _ = proxy._published_books(path, original, _Upstream())
    assert payload is original


def test_a_failed_response_is_forwarded_untouched():
    from backend.api.routers import cockpit_v4_proxy as proxy

    class _Upstream:
        status_code = 503
        headers = {"content-type": "application/json"}

    original = b'{"error": "unavailable"}'
    payload, _ = proxy._published_books("domains", original, _Upstream())
    assert payload is original


def test_hop_by_hop_headers_do_not_cross_the_boundary():
    """They belong to one connection; forwarding them corrupts the next."""
    from backend.api.routers import cockpit_v4_proxy as proxy

    for header in ("connection", "keep-alive", "transfer-encoding",
                   "content-length", "content-encoding", "host", "upgrade"):
        assert header in proxy._DROP, header


def test_a_caller_cannot_contribute_the_boundary_headers(monkeypatch):
    """Whatever the spelling, the caller's copy does not travel.

    Starlette normalises header names, so in practice an inbound
    `X-Cockpit-Principal` arrives lowercased and is replaced. This asserts
    the property rather than the current behaviour of the framework
    underneath it: the outbound dict is built lowercased AND the two
    boundary names are dropped before either is written.
    """
    from backend.api.routers import cockpit_v4_proxy as proxy

    monkeypatch.setenv(identity.SECRET_VAR, "the-real-one")
    monkeypatch.setenv(identity.TENANT_VAR, "demo-tenant")

    class _Req:
        headers = {
            "X-Cockpit-Principal": json.dumps({"id": "attacker",
                                               "tenant": "someone-else"}),
            "X-Cockpit-Auth": "guessed",
            "Accept-Encoding": "gzip, br",
            "Cookie": "session=abc",
        }

    out = proxy._outbound(_Req(), {"id": "u1", "tenant": "demo-tenant"})
    assert set(out) == {k.lower() for k in out}, "keys must be lowercased"
    assert json.loads(out[identity.PRINCIPAL_HEADER])["id"] == "u1"
    assert out[identity.AUTH_HEADER] == "the-real-one"
    assert "attacker" not in json.dumps(out)
    # And a stream is never compressed.
    assert out["accept-encoding"] == "identity"
