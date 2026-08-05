"""
A person on no team gets an amebo.

Somebody screened into the workers.vc applicant pool belongs to no org. That is
a real state, not a broken one: amebo already separates the instance (which
amebo answers) from the org (whose work it may touch), so a person with zero
memberships is representable. What was missing was the sign-in rule — an
identity with no membership got no person record at all — and a way to pick an
instance when there is no org to pick it from.

Nothing here gives them access to anybody's work. org_context stays None for a
session with no org, so every org-scoped tool keeps refusing them through
OrgResolver, exactly as before.

Golda 2026-08-05: "they should get a person record and a session, and then we
can put some nudges, rules, claws for them."
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Asking GovKit who a login is
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status_code, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def people():
    from src.integrations.govkit_directory import GovKitPeople

    return GovKitPeople(base_url="https://dash.workers.vc", token="s3cret")


POOL_PAYLOAD = {
    "display_name": "Ada Example",
    "email": "ada@example.org",
    "pool": True,
    "memberships": [],
}


class TestGovKitIdentity:
    def test_a_person_in_the_pool_comes_back_as_someone(self, people):
        with patch("src.integrations.govkit_directory.requests.get") as get:
            get.return_value = _Resp(200, POOL_PAYLOAD)
            identity = people.identity("sub-ada")

        assert identity.pool is True
        assert identity.memberships == ()
        assert identity.email == "ada@example.org"
        assert "/api/v1/accounts/s2s/identity/linkedtrust/sub-ada/" in get.call_args.args[0]
        assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer s3cret"

    def test_a_member_is_not_in_the_pool(self, people):
        with patch("src.integrations.govkit_directory.requests.get") as get:
            get.return_value = _Resp(200, {
                "display_name": "Bo", "email": "bo@example.org", "pool": False,
                "memberships": [{"org_slug": "wayfern", "role": "admin"}],
            })
            identity = people.identity("sub-bo")

        assert identity.pool is False
        assert identity.memberships[0]["org_slug"] == "wayfern"

    def test_a_stranger_is_none(self, people):
        with patch("src.integrations.govkit_directory.requests.get") as get:
            get.return_value = _Resp(404)
            assert people.identity("nobody") is None

    def test_an_outage_is_none_not_an_answer(self, people):
        import requests as requests_lib

        with patch("src.integrations.govkit_directory.requests.get") as get:
            get.side_effect = requests_lib.RequestException("down")
            assert people.identity("sub-ada") is None

    def test_garbage_is_none(self, people):
        with patch("src.integrations.govkit_directory.requests.get") as get:
            get.return_value = _Resp(200, bad_json=True)
            assert people.identity("sub-ada") is None

    def test_no_govkit_configured_asks_nobody(self):
        from src.integrations.govkit_directory import GovKitPeople

        with patch("src.integrations.govkit_directory.requests.get") as get:
            assert GovKitPeople(base_url="", token="").identity("sub-ada") is None
        get.assert_not_called()


# ---------------------------------------------------------------------------
# The sign-in rule
# ---------------------------------------------------------------------------


class TestTheGateFailsClosed:
    """An outage must not turn strangers into members. Somebody in the pool
    having to sign in again in five minutes is the cheaper failure."""

    def _check(self, identity=None, boom=False):
        from src.api.routes.auth import _is_in_the_pool

        fake = MagicMock()
        if boom:
            fake.return_value.identity.side_effect = RuntimeError("boom")
        else:
            fake.return_value.identity.return_value = identity
        with patch("src.integrations.govkit_directory.GovKitPeople", fake):
            return _is_in_the_pool("sub-ada")

    def test_govkit_says_pool_so_they_are_admitted(self):
        from src.integrations.govkit_directory import Identity

        assert self._check(Identity("Ada", "ada@example.org", True, ())) is True

    def test_govkit_says_not_pool(self):
        from src.integrations.govkit_directory import Identity

        assert self._check(Identity("Bo", "bo@example.org", False, ())) is False

    def test_govkit_does_not_know_them(self):
        assert self._check(None) is False

    def test_govkit_blew_up(self):
        assert self._check(boom=True) is False


# ---------------------------------------------------------------------------
# Which amebo answers a person with no org
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    from src.api.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app):
    import asyncio

    transport = httpx.ASGITransport(app=app)

    class _SyncFacade:
        def post(self, path, **kwargs):
            async def _do():
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://testserver"
                ) as ac:
                    return await ac.post(path, **kwargs)

            return asyncio.run(_do())

    return _SyncFacade()


@pytest.fixture
def as_pool_worker(app):
    """Signed in, recognized, and on no team — org_id is NULL."""
    from src.api.middleware.auth import get_current_user

    user = {"user_id": 7, "org_id": None, "email": "ada@example.org", "role": "member"}
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)


DEFAULT_INSTANCE = {"id": 3, "slug": "vc", "org_id": None}


class TestTheDefaultInstance:
    def _ask(self, client, env):
        with patch.dict("os.environ", env, clear=False), \
             patch("src.api.routes.chat.InstanceRepo") as repo, \
             patch("src.api.routes.chat.QAService") as qa:
            repo.return_value.get_by_slug.return_value = DEFAULT_INSTANCE
            repo.return_value.get_by_org.return_value = None
            qa.return_value.answer_question.return_value = {"answer": "hello"}
            resp = client.post("/api/chat/message", json={"message": "hi"})
        return resp, repo, qa

    def test_a_person_with_no_org_reaches_this_deployment_s_amebo(
        self, client, as_pool_worker
    ):
        resp, repo, _ = self._ask(client, {"AMEBO_DEFAULT_INSTANCE_SLUG": "vc"})

        assert resp.status_code == 200
        repo.return_value.get_by_slug.assert_called_once_with("vc")
        repo.return_value.get_by_org.assert_not_called()

    def test_they_still_get_no_org_context_so_no_org_scoped_tool_runs(
        self, client, as_pool_worker
    ):
        _, _, qa = self._ask(client, {"AMEBO_DEFAULT_INSTANCE_SLUG": "vc"})

        assert qa.call_args.kwargs["org_context"] is None
        assert qa.call_args.kwargs["org_id"] is None

    def test_a_deployment_that_names_no_default_is_unchanged(
        self, client, as_pool_worker
    ):
        resp, repo, _ = self._ask(client, {"AMEBO_DEFAULT_INSTANCE_SLUG": ""})

        assert resp.status_code == 404
        repo.return_value.get_by_slug.assert_not_called()
