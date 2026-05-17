"""
Tests for the http_fetch tool.

External network is not hit. The requests session is patched so we can
exercise the safety paths (scheme rejection, internal-IP rejection,
redirect revalidation, size cap, content-type filter, timeouts) without
flakiness.

DNS resolution IS exercised for hostname → IP, but mocked through socket
patches so tests stay offline.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import requests

from src.tools.http_fetch import http_fetch


def _addrinfo_for(ip: str):
    return [(0, 0, 0, "", (ip, 0))]


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestArgValidation:
    def test_missing_url(self):
        out = http_fetch({}, {})
        assert "url is required" in out.lower()

    def test_disallowed_scheme(self):
        out = http_fetch({"url": "ftp://example.com/x"}, {})
        assert "scheme" in out.lower()

    def test_no_hostname(self):
        out = http_fetch({"url": "http:///path"}, {})
        assert "hostname" in out.lower()


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------


class TestSSRFProtection:
    def test_loopback_rejected(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("127.0.0.1")):
            out = http_fetch({"url": "http://localhost/x"}, {})
        assert "non-public" in out.lower() or "refusing" in out.lower()

    def test_private_10_rejected(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("10.0.0.42")):
            out = http_fetch({"url": "http://internal.example/x"}, {})
        assert "non-public" in out.lower()

    def test_private_192_rejected(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("192.168.1.1")):
            out = http_fetch({"url": "http://router.local/x"}, {})
        assert "non-public" in out.lower()

    def test_link_local_rejected(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("169.254.169.254")):
            out = http_fetch({"url": "http://metadata.internal/x"}, {})
        assert "non-public" in out.lower()

    def test_dns_failure_rejected(self):
        import socket as socket_module
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   side_effect=socket_module.gaierror("nope")):
            out = http_fetch({"url": "http://nonexistent.invalid/x"}, {})
        assert "dns" in out.lower()


# ---------------------------------------------------------------------------
# Fetch behavior
# ---------------------------------------------------------------------------


def _make_mock_response(status=200, headers=None, body=b"hello world",
                       url="https://example.com/x"):
    """Build a mock requests Response that works as a context manager + iterator."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = headers or {"Content-Type": "text/plain"}
    resp.url = url
    resp.encoding = "utf-8"

    def iter_chunks(chunk_size=8192, decode_unicode=False):
        # one chunk of body
        yield body
    resp.iter_content = iter_chunks

    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFetchSuccess:
    def test_returns_text_body(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("93.184.216.34")), \
             patch("requests.Session.get",
                   return_value=_make_mock_response(body=b"hello there")):
            out = http_fetch({"url": "https://example.com/page"}, {})
        assert "hello there" in out
        assert "Status: 200" in out

    def test_json_content_type_allowed(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("93.184.216.34")), \
             patch("requests.Session.get",
                   return_value=_make_mock_response(
                       headers={"Content-Type": "application/json"},
                       body=b'{"k":"v"}')):
            out = http_fetch({"url": "https://example.com/api"}, {})
        assert '{"k":"v"}' in out

    def test_binary_content_rejected(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("93.184.216.34")), \
             patch("requests.Session.get",
                   return_value=_make_mock_response(
                       headers={"Content-Type": "image/png"},
                       body=b"\x89PNG\r\n")):
            out = http_fetch({"url": "https://example.com/img.png"}, {})
        assert "non-text" in out.lower()


class TestRedirectRevalidation:
    def test_redirect_to_internal_rejected(self):
        # Final response object's URL points at an internal IP — must be re-checked
        with patch("src.tools.http_fetch.socket.getaddrinfo") as getaddrinfo, \
             patch("requests.Session.get") as session_get:
            # First call (initial host) returns public IP; second (redirect target)
            # returns a loopback address.
            getaddrinfo.side_effect = [
                _addrinfo_for("93.184.216.34"),
                _addrinfo_for("127.0.0.1"),
            ]
            session_get.return_value = _make_mock_response(
                url="http://localhost/inside",
            )
            out = http_fetch({"url": "http://example.com/x"}, {})
        assert "redirect target rejected" in out.lower()


class TestErrorPaths:
    def test_timeout(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("93.184.216.34")), \
             patch("requests.Session.get",
                   side_effect=requests.exceptions.Timeout()):
            out = http_fetch({"url": "https://example.com/slow"}, {})
        assert "timed out" in out.lower()

    def test_too_many_redirects(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("93.184.216.34")), \
             patch("requests.Session.get",
                   side_effect=requests.exceptions.TooManyRedirects()):
            out = http_fetch({"url": "https://example.com/loop"}, {})
        assert "redirects" in out.lower()

    def test_ssl_error(self):
        with patch("src.tools.http_fetch.socket.getaddrinfo",
                   return_value=_addrinfo_for("93.184.216.34")), \
             patch("requests.Session.get",
                   side_effect=requests.exceptions.SSLError("bad cert")):
            out = http_fetch({"url": "https://bad.example/x"}, {})
        assert "ssl" in out.lower()
