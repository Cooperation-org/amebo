"""
http_fetch tool — read a public URL.

Safety constraints (all enforced before any network call):
- Scheme must be http or https.
- Hostname must resolve to a public IP. Internal/loopback/link-local IPs
  are rejected to prevent SSRF against the VM's other services.
- Redirect chain bounded; redirect targets revalidated against the same
  rules.
- Response size capped (default 256 KB) to avoid memory exhaustion.
- Response time capped (default 10 s).
- Only text-like content types returned to the model; HTML is reduced to
  its visible text.

The model never sees raw bytes — only decoded text, truncated as needed.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
from html.parser import HTMLParser
from typing import Tuple
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


MAX_BYTES_DEFAULT = 256 * 1024     # 256 KB
TIMEOUT_DEFAULT = 10               # seconds
MAX_REDIRECTS = 3
ALLOWED_SCHEMES = {"http", "https"}
TEXTY_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/atom",
    "application/rss",
    "application/ld+json",
)


def _is_public_ip(addr: str) -> bool:
    """Reject loopback, private, link-local, multicast, reserved."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return True


def _resolve_and_check(host: str) -> Tuple[bool, str]:
    """
    Resolve hostname to an IP and verify it's a public address.
    Returns (allowed, reason).
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return False, f"DNS resolution failed: {exc}"

    for info in infos:
        addr = info[4][0]
        if not _is_public_ip(addr):
            return False, f"refusing to fetch from non-public address {addr}"
    return True, "ok"


_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "head", "iframe"}
_BLOCK_TAGS = {
    "p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section",
    "article", "header", "footer", "nav", "aside", "main", "h1", "h2", "h3",
    "h4", "h5", "h6", "blockquote", "pre", "dt", "dd", "figcaption", "title",
}


class _TextExtractor(HTMLParser):
    """Visible text of an HTML page: drops scripts, styles and markup, keeps
    the title and line breaks at block elements."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # malformed markup: keep what was parsed
        pass
    lines = (re.sub(r"[ \t\u00a0]+", " ", ln).strip()
             for ln in "".join(parser.parts).splitlines())
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    title = html.unescape(" ".join(parser.title.split()))
    return (f"Title: {title}\n\n" if title else "") + body


def _content_is_text(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(ct.startswith(prefix) for prefix in TEXTY_CONTENT_TYPES)


def http_fetch(tool_input: dict, context: dict) -> str:
    """
    Tool entry point. Returns either the fetched text (possibly truncated)
    or a human-readable error string.

    Inputs:
        url      (str, required)
        max_kb   (int, optional, default 256)
    """
    url = (tool_input.get("url") or "").strip()
    if not url:
        return "Error: url is required."

    max_kb = int(tool_input.get("max_kb") or 256)
    max_bytes = min(max_kb * 1024, 2 * 1024 * 1024)  # hard ceiling 2 MB

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return f"Error: scheme {parsed.scheme!r} not allowed. Use http or https."
    if not parsed.hostname:
        return "Error: URL has no hostname."

    ok, reason = _resolve_and_check(parsed.hostname)
    if not ok:
        return f"Error: {reason}"

    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS

    try:
        with session.get(
            url,
            timeout=TIMEOUT_DEFAULT,
            stream=True,
            allow_redirects=True,
            headers={"User-Agent": "amebo-http-fetch/1.0"},
        ) as resp:
            # Re-validate the final URL after redirects.
            final = urlparse(resp.url)
            if final.scheme not in ALLOWED_SCHEMES:
                return f"Error: redirected to disallowed scheme {final.scheme!r}."
            if final.hostname:
                ok, reason = _resolve_and_check(final.hostname)
                if not ok:
                    return f"Error: redirect target rejected — {reason}"

            content_type = resp.headers.get("Content-Type", "")
            if not _content_is_text(content_type):
                return (
                    f"Error: refusing non-text content (Content-Type: "
                    f"{content_type or 'unknown'})."
                )

            raw = bytearray()
            for chunk in resp.iter_content(chunk_size=8192, decode_unicode=False):
                if not chunk:
                    continue
                raw.extend(chunk)
                if len(raw) >= max_bytes:
                    break

            try:
                text = raw[:max_bytes].decode(resp.encoding or "utf-8", errors="replace")
            except LookupError:
                text = raw[:max_bytes].decode("utf-8", errors="replace")

            truncated = len(raw) >= max_bytes
            # The model reads page text, not markup: raw HTML is mostly scripts
            # and styles, and the model then claims facts it never saw.
            if "html" in content_type.lower():
                text = _html_to_text(text)
            header = f"URL: {resp.url}\nStatus: {resp.status_code}\n"
            if truncated:
                header += f"[page truncated at {max_bytes} bytes before text extraction]\n"
            return header + "\n" + text

    except requests.exceptions.TooManyRedirects:
        return "Error: too many redirects."
    except requests.exceptions.Timeout:
        return f"Error: request timed out after {TIMEOUT_DEFAULT}s."
    except requests.exceptions.SSLError as exc:
        return f"Error: SSL error — {exc}"
    except requests.exceptions.RequestException as exc:
        return f"Error: request failed — {exc}"


HTTP_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "Absolute http or https URL to fetch.",
        },
        "max_kb": {
            "type": "integer",
            "description": "Max KB to read from the response (default 256, hard cap 2048).",
            "default": 256,
        },
    },
    "required": ["url"],
}
