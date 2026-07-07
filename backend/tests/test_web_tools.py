"""
web_search / web_research tool tests. All network calls mocked — no real
You.com requests. Mirrors test_http_fetch.py conventions.
"""

from __future__ import annotations

from unittest.mock import patch

from src.services import gated_actions
from src.tools import web_tools
from src.tools.registry import _TOOLS


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


SEARCH_BODY = {
    "results": {
        "web": [
            {
                "url": "https://example.com/a",
                "title": "Example A",
                "description": "First result",
                "snippets": ["First result", "extra snippet"],
            }
        ],
        "news": [],
    },
    "metadata": {"query": "example"},
}

RESEARCH_BODY = {
    "output": {
        "content": "Answer with citation [1].",
        "content_type": "text",
        "sources": [{"url": "https://example.com/a", "title": "Example A"}],
    }
}


class TestWebSearch:
    def test_requires_query(self):
        assert "query is required" in web_tools.web_search({}, {})

    def test_happy_path_formats_results(self):
        with patch.object(web_tools.requests, "get",
                          return_value=FakeResponse(200, SEARCH_BODY)) as m:
            out = web_tools.web_search({"query": "example"}, {})
        assert "Example A" in out
        assert "https://example.com/a" in out
        _, kwargs = m.call_args
        assert kwargs["params"]["query"] == "example"
        assert kwargs["params"]["count"] == 10

    def test_count_clamped(self):
        with patch.object(web_tools.requests, "get",
                          return_value=FakeResponse(200, SEARCH_BODY)) as m:
            web_tools.web_search({"query": "x", "count": 999}, {})
        assert m.call_args.kwargs["params"]["count"] == web_tools.MAX_COUNT

    def test_no_results(self):
        body = {"results": {"web": [], "news": []}}
        with patch.object(web_tools.requests, "get",
                          return_value=FakeResponse(200, body)):
            out = web_tools.web_search({"query": "nothing"}, {})
        assert out.startswith("No results")

    def test_rate_limit_maps_to_message(self):
        with patch.object(web_tools.requests, "get",
                          return_value=FakeResponse(429)):
            out = web_tools.web_search({"query": "x"}, {})
        assert "429" in out

    def test_keyless_has_no_auth_header(self, monkeypatch):
        monkeypatch.delenv("YDC_API_KEY", raising=False)
        with patch.object(web_tools.requests, "get",
                          return_value=FakeResponse(200, SEARCH_BODY)) as m:
            web_tools.web_search({"query": "x"}, {})
        assert "X-API-Key" not in m.call_args.kwargs["headers"]

    def test_key_sent_when_configured(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "sekret")
        with patch.object(web_tools.requests, "get",
                          return_value=FakeResponse(200, SEARCH_BODY)) as m:
            web_tools.web_search({"query": "x"}, {})
        assert m.call_args.kwargs["headers"]["X-API-Key"] == "sekret"


class TestWebResearch:
    def test_requires_question(self):
        assert "question is required" in web_tools.web_research({}, {})

    def test_requires_key(self, monkeypatch):
        monkeypatch.delenv("YDC_API_KEY", raising=False)
        out = web_tools.web_research({"question": "why?"}, {})
        assert "YDC_API_KEY" in out

    def test_happy_path(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "sekret")
        with patch.object(web_tools.requests, "post",
                          return_value=FakeResponse(200, RESEARCH_BODY)) as m:
            out = web_tools.web_research({"question": "why?"}, {})
        assert "Answer with citation" in out
        assert "Sources:" in out
        assert m.call_args.kwargs["json"]["research_effort"] == "standard"

    def test_rejects_bad_effort(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "sekret")
        out = web_tools.web_research({"question": "q", "effort": "max"}, {})
        assert "effort must be one of" in out

    def test_invalid_key_maps_to_message(self, monkeypatch):
        monkeypatch.setenv("YDC_API_KEY", "bad")
        with patch.object(web_tools.requests, "post",
                          return_value=FakeResponse(401)):
            out = web_tools.web_research({"question": "q"}, {})
        assert "401" in out


class TestWiring:
    def test_registered(self):
        assert "web_search" in _TOOLS
        assert "web_research" in _TOOLS
        assert _TOOLS["web_search"].is_read_only
        assert _TOOLS["web_research"].is_read_only

    def test_free_actions(self):
        assert not gated_actions.requires_approval("web_search")
        assert not gated_actions.requires_approval("web_research")
