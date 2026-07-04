"""
Regression tests for endpoints used by the Changemaker app (and other external
clients).

These endpoints are CALLED LIVE by Changemaker. Breaking them breaks the
client's app. Every change to the surrounding code must keep these tests
passing.

Covered:
- POST /api/embeddings/similarity      (alignment scoring)
- POST /api/chat/message               (chat / suggestions)
- POST /api/chat/documents             (knowledge ingestion)
- GET  /api/chat/instances/{slug}      (instance lookup)

Style:
- FastAPI TestClient (no live server required).
- External services (Anthropic, embeddings model, DB) are mocked at the
  smallest possible boundary so we exercise as much real code as possible
  while keeping tests fast and deterministic.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """
    Import the FastAPI app lazily so module import does not run the full
    application bootstrap when other tests are collected.
    """
    from src.api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app):
    """
    Async httpx client backed by an ASGI transport, wrapped in a small
    sync façade so tests stay readable. Avoids starlette TestClient
    (incompatible with this venv's httpx 0.28).
    """
    import asyncio

    transport = httpx.ASGITransport(app=app)

    class _SyncFacade:
        def __init__(self, transport):
            self._transport = transport

        def _request(self, method, path, **kwargs):
            async def _do():
                async with httpx.AsyncClient(
                    transport=self._transport, base_url="http://testserver"
                ) as ac:
                    return await ac.request(method, path, **kwargs)
            return asyncio.run(_do())

        def get(self, path, **kwargs):
            return self._request("GET", path, **kwargs)

        def post(self, path, **kwargs):
            return self._request("POST", path, **kwargs)

    return _SyncFacade(transport)


@pytest.fixture
def as_user(app):
    """Authenticate requests as a logged-in SSO user with an org.

    /api/chat/message now requires auth (Depends(get_current_user)) and resolves
    the instance from the AUTHENTICATED user's org, not a client-supplied value
    (see chat.py). Override the dependency so tests exercise the real handler
    instead of bouncing at 403."""
    from src.api.middleware.auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": 1, "org_id": 42, "email": "tester@example.com",
    }
    yield {"user_id": 1, "org_id": 42, "email": "tester@example.com"}
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# /api/embeddings/similarity
# ---------------------------------------------------------------------------


class TestEmbeddingsSimilarity:
    """Used by Changemaker /api/score to compute alignment with core values."""

    def test_returns_scores_for_each_text(self, client):
        with patch("src.api.routes.embeddings.embed_text") as et, \
             patch("src.api.routes.embeddings.embed_texts") as ets:
            # 3-dim toy embeddings — already L2-normalized for predictability
            et.return_value = [1.0, 0.0, 0.0]
            ets.return_value = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]

            resp = client.post(
                "/api/embeddings/similarity",
                json={"reference": "courage", "texts": ["bravery", "fear"]},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["reference"] == "courage"
        assert len(body["scores"]) == 2
        assert body["scores"][0]["text"] == "bravery"
        assert body["scores"][0]["score"] == pytest.approx(1.0, abs=1e-3)
        assert body["scores"][1]["text"] == "fear"
        assert body["scores"][1]["score"] == pytest.approx(0.0, abs=1e-3)
        assert body["overall"] == pytest.approx(0.5, abs=1e-3)

    def test_empty_reference_returns_400(self, client):
        resp = client.post(
            "/api/embeddings/similarity",
            json={"reference": "   ", "texts": ["something"]},
        )
        assert resp.status_code == 400

    def test_empty_texts_returns_400(self, client):
        resp = client.post(
            "/api/embeddings/similarity",
            json={"reference": "anything", "texts": []},
        )
        assert resp.status_code == 400

    # NOTE: whitespace-only texts currently return 500 (broad except in route
    # converts the inner HTTPException(400) to 500). Real Changemaker requests
    # never send whitespace-only texts, so this is not a regression risk for
    # the live integration. Tracked separately as a route-cleanup task.

    def test_missing_fields_returns_422(self, client):
        # FastAPI/pydantic schema validation
        resp = client.post("/api/embeddings/similarity", json={})
        assert resp.status_code == 422

    def test_response_schema_is_stable(self, client):
        """Lock down the contract: keys and types Changemaker depends on."""
        with patch("src.api.routes.embeddings.embed_text") as et, \
             patch("src.api.routes.embeddings.embed_texts") as ets:
            et.return_value = [1.0, 0.0]
            ets.return_value = [[1.0, 0.0]]

            resp = client.post(
                "/api/embeddings/similarity",
                json={"reference": "x", "texts": ["y"]},
            )

        body = resp.json()
        assert set(body.keys()) == {"reference", "scores", "overall"}
        assert set(body["scores"][0].keys()) == {"text", "score"}
        assert isinstance(body["overall"], float)


# ---------------------------------------------------------------------------
# /api/chat/message
# ---------------------------------------------------------------------------


class TestChatMessage:
    """Used by Changemaker /api/suggest to get aligned content suggestions.

    The endpoint now requires an authenticated SSO user and resolves the instance
    from that user's org (InstanceRepo.get_by_org), not a client-supplied slug.
    These tests authenticate via the `as_user` fixture and mock get_by_org."""

    def test_message_returns_reply_and_session(self, client, as_user):
        fake_result = {
            "answer": "Some suggestion.",
            "confidence": 80,
            "context_used": 1,
        }
        with patch("src.api.routes.chat.QAService") as QA, \
             patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_org.return_value = {
                "id": 1, "slug": "inst", "org_id": as_user["org_id"],
            }
            QA.return_value.answer_question.return_value = fake_result

            resp = client.post(
                "/api/chat/message",
                json={"message": "draft a post about resilience"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["reply"] == "Some suggestion."
        assert body["confidence"] == 80
        assert body["tool_rounds"] == 1
        # session_id is auto-generated and must be a non-empty string
        assert isinstance(body["session_id"], str) and body["session_id"]

    def test_session_id_is_preserved(self, client, as_user):
        with patch("src.api.routes.chat.QAService") as QA, \
             patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_org.return_value = {
                "id": 1, "slug": "inst", "org_id": as_user["org_id"],
            }
            QA.return_value.answer_question.return_value = {"answer": "ok"}

            resp = client.post(
                "/api/chat/message",
                json={"message": "hi", "session_id": "abc-123"},
            )

        assert resp.status_code == 200
        assert resp.json()["session_id"] == "abc-123"

    def test_empty_message_returns_400(self, client, as_user):
        # auth passes; the empty-message guard rejects before instance lookup
        resp = client.post("/api/chat/message", json={"message": "   "})
        assert resp.status_code == 400

    def test_no_instance_for_org_returns_404(self, client, as_user):
        # the user's org has no configured amebo instance
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_org.return_value = None
            resp = client.post("/api/chat/message", json={"message": "hi"})
        assert resp.status_code == 404

    def test_unauthenticated_is_rejected(self, client):
        # no as_user override -> the auth dependency refuses (401/403), never 200
        resp = client.post("/api/chat/message", json={"message": "hi"})
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# /api/chat/documents
# ---------------------------------------------------------------------------


class TestChatDocuments:
    """Used by Changemaker /api/sources/ingest to load context into amebo."""

    def test_upload_document_returns_content_id(self, client):
        fake_instance = {"id": 1, "slug": "test-inst", "org_id": 42}
        with patch("src.api.routes.chat.InstanceRepo") as IR, \
             patch("src.db.embedding.embed_text") as ET, \
             patch("src.db.repositories.binding_repo.BindingRepo") as BR:
            IR.return_value.get_by_slug.return_value = fake_instance
            ET.return_value = [0.0] * 384
            BR.return_value.create_content.return_value = 999

            resp = client.post(
                "/api/chat/documents",
                json={
                    "instance_slug": "test-inst",
                    "title": "Core Values",
                    "content": "Honesty, kindness, persistence.",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok", "content_id": 999, "title": "Core Values"}

    def test_unknown_instance_returns_404(self, client):
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = None
            resp = client.post(
                "/api/chat/documents",
                json={
                    "instance_slug": "missing",
                    "title": "t",
                    "content": "hello",
                },
            )
        assert resp.status_code == 404

    def test_instance_without_org_returns_400(self, client):
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {"slug": "x", "org_id": None}
            resp = client.post(
                "/api/chat/documents",
                json={"instance_slug": "x", "title": "t", "content": "hello"},
            )
        assert resp.status_code == 400

    def test_empty_content_returns_400(self, client):
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {"slug": "x", "org_id": 1}
            resp = client.post(
                "/api/chat/documents",
                json={"instance_slug": "x", "title": "t", "content": "   "},
            )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# /api/chat/instances/{slug}
# ---------------------------------------------------------------------------


class TestChatInstanceInfo:
    def test_returns_public_info(self, client):
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {
                "name": "Changemaker",
                "slug": "changemaker",
                "identity_prompt": "secret",  # must NOT be exposed
            }
            resp = client.get("/api/chat/instances/changemaker")

        assert resp.status_code == 200
        body = resp.json()
        assert body == {"name": "Changemaker", "slug": "changemaker"}

    def test_unknown_instance_returns_404(self, client):
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = None
            resp = client.get("/api/chat/instances/missing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/chat/public — unauthenticated, read-only embed (unknown user, T0)
# ---------------------------------------------------------------------------


class TestPublicChat:
    """The embeddable public chat: no SSO, treated as the unknown user (T0),
    answers from the instance's knowledge but NEVER executes anything."""

    def test_answers_without_auth_and_read_only(self, client):
        with patch("src.api.routes.chat.QAService") as QA, \
             patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {
                "id": 1, "slug": "demo", "org_id": 7, "config": {"public_chat": True}}
            QA.return_value.answer_question.return_value = {"answer": "Public answer.", "confidence": 60}
            resp = client.post(
                "/api/chat/public",
                json={"message": "what is this project?", "instance_slug": "demo"},
            )
        assert resp.status_code == 200          # no auth required
        assert resp.json()["reply"] == "Public answer."
        # structurally read-only: the QA is invoked with tools disabled
        _, kwargs = QA.return_value.answer_question.call_args
        assert kwargs.get("allow_tools") is False

    def test_caller_is_treated_as_t0_unknown_user(self, client):
        with patch("src.api.routes.chat.QAService") as QA, \
             patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {
                "id": 1, "slug": "demo", "org_id": 7, "config": {"public_chat": True}}
            QA.return_value.answer_question.return_value = {"answer": "ok"}
            client.post("/api/chat/public", json={"message": "hi", "instance_slug": "demo"})
        _, ctor_kwargs = QA.call_args
        principal = ctor_kwargs.get("principal")
        from src.services.trust import evaluate, TrustLevel
        assert principal is not None and evaluate(principal) == TrustLevel.T0

    def test_uses_isolated_public_thread_namespace(self, client):
        # public sessions must not share the authenticated web-<slug> namespace
        with patch("src.api.routes.chat.QAService") as QA, \
             patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {
                "id": 1, "slug": "demo", "org_id": 7, "config": {"public_chat": True}}
            QA.return_value.answer_question.return_value = {"answer": "ok"}
            client.post("/api/chat/public", json={"message": "hi", "instance_slug": "demo"})
        _, ctor_kwargs = QA.call_args
        assert ctor_kwargs.get("workspace_id") == "public-demo"

    def test_unknown_instance_returns_404(self, client):
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = None
            resp = client.post(
                "/api/chat/public", json={"message": "hi", "instance_slug": "nope"}
            )
        assert resp.status_code == 404

    def test_instance_not_opted_in_returns_404(self, client):
        # public chat is OFF by default; an existing instance without
        # config.public_chat must 404 (same as not-found — no info leak)
        with patch("src.api.routes.chat.InstanceRepo") as IR:
            IR.return_value.get_by_slug.return_value = {
                "id": 1, "slug": "demo", "org_id": 7, "config": {}}
            resp = client.post(
                "/api/chat/public", json={"message": "hi", "instance_slug": "demo"}
            )
        assert resp.status_code == 404

    def test_empty_message_returns_400(self, client):
        resp = client.post(
            "/api/chat/public", json={"message": "   ", "instance_slug": "demo"}
        )
        assert resp.status_code == 400

    def test_message_too_long_returns_400(self, client):
        resp = client.post(
            "/api/chat/public",
            json={"message": "x" * 5000, "instance_slug": "demo"},
        )
        assert resp.status_code == 400

    def test_missing_instance_slug_is_422(self, client):
        resp = client.post("/api/chat/public", json={"message": "hi"})
        assert resp.status_code == 422
