"""amebo on Bluesky: answer the owner's @-mentions with a Claude Code turn on the
Max login, the same way amebo-max answers Slack (src/services/max_answerer.py).

Who it answers: only the accounts in AMEBO_BLUESKY_OWNERS, matched by DID (a
handle can change hands; a DID cannot). Everyone else is marked handled and
never answered. Posts by other people in the thread (the post being replied to,
a quoted post, a link card) reach Claude as data inside <bluesky_thread> tags.

How it hears: polls app.bsky.notification.listNotifications. Each handled
notification URI is appended to a file the moment it is handled, so a restart
answers nothing twice. On the first run every existing notification is marked
handled, so old mentions are not answered.

Limits: ClaudeMax's hourly cap and daily rest. A mention that arrives while
amebo is resting or at its cap stays unhandled and is answered on a later poll.

One Claude session per Bluesky thread (uuid5 of the root post URI), resumed on
each later mention in that thread.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import httpx

from src.services.max_answerer import ClaudeMax, scan_text, system_prompt

logger = logging.getLogger(__name__)

POST_LIMIT = 300          # Bluesky's limit is 300 graphemes; code points never undercount
MAX_POSTS = 4             # longest reply chain one answer may post
BLUESKY_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "amebo-bluesky.md"
_URL = re.compile(r"https?://[^\s<>\"')\]]+")


def thread_session_id(root_uri: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bluesky:{root_uri}"))


def post_url(post: Dict[str, Any]) -> str:
    """bsky.app link for a post view."""
    rkey = post["uri"].rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{post['author']['handle']}/post/{rkey}"


def _embed_lines(embed: Optional[Dict[str, Any]]) -> List[str]:
    """Link cards and quoted posts, which carry most of what a post points at."""
    if not embed:
        return []
    out = []
    ext = embed.get("external")
    if ext:
        out.append(f"  link: {ext.get('uri', '')} | {ext.get('title', '')} | {ext.get('description', '')}")
    rec = embed.get("record") or {}
    rec = rec.get("record", rec)          # recordWithMedia nests one level deeper
    if rec.get("value", {}).get("text") and rec.get("author"):
        out.append(f"  quotes @{rec['author']['handle']}: {rec['value']['text']}")
    if embed.get("media"):
        out += _embed_lines(embed["media"])
    return out


def format_thread(chain: List[Dict[str, Any]], bot_did: str) -> str:
    """Posts oldest first; the last one is the request."""
    lines = []
    for i, post in enumerate(chain):
        who = "amebo" if post["author"]["did"] == bot_did else "@" + post["author"]["handle"]
        mark = ' latest="true"' if i == len(chain) - 1 else ""
        lines.append(f'<post by="{who}" url="{post_url(post)}"{mark}>')
        lines.append(post.get("record", {}).get("text", ""))
        lines += _embed_lines(post.get("embed"))
        lines.append("</post>")
    return "<bluesky_thread>\n" + "\n".join(lines) + "\n</bluesky_thread>"


def thread_chain(thread: Dict[str, Any]) -> List[Dict[str, Any]]:
    """getPostThread's nested parents, flattened oldest first. Deleted or
    blocked parents end the chain."""
    chain = []
    node = thread
    while node and node.get("post"):
        chain.append(node["post"])
        node = node.get("parent")
    return list(reversed(chain))


def split_reply(text: str, limit: int = POST_LIMIT, max_posts: int = MAX_POSTS) -> List[str]:
    """Paragraphs, then sentences, then words, packed into posts of at most
    `limit` characters. Past `max_posts` the last post is cut with an ellipsis."""
    pieces: List[str] = []
    for para in [p.strip() for p in text.strip().split("\n\n") if p.strip()]:
        if len(para) <= limit:
            pieces.append(para)
            continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            while len(sent) > limit:
                cut = sent.rfind(" ", 0, limit) if " " in sent[:limit] else limit
                pieces.append(sent[:cut].strip())
                sent = sent[cut:].strip()
            if sent:
                pieces.append(sent)
    posts: List[str] = []
    for piece in pieces:
        sep = "\n\n" if posts and "\n" not in piece and posts[-1].endswith((".", "!", "?", ":")) else " "
        if posts and len(posts[-1]) + len(sep) + len(piece) <= limit:
            posts[-1] += sep + piece
        else:
            posts.append(piece)
    if len(posts) > max_posts:
        posts = posts[:max_posts]
        posts[-1] = posts[-1][:limit - 1].rstrip() + "…"
    return posts


def link_facets(text: str) -> List[Dict[str, Any]]:
    """Bluesky shows a URL as a link only when a facet marks its UTF-8 byte range."""
    facets = []
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(".,;:!?")
        start = len(text[:m.start()].encode())
        facets.append({
            "index": {"byteStart": start, "byteEnd": start + len(url.encode())},
            "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
        })
    return facets


def addresses_bot(notif: Dict[str, Any], bot_did: str) -> bool:
    """A mention facet naming the bot, or a direct reply to one of its posts."""
    record = notif.get("record", {})
    if notif.get("reason") == "reply":
        parent = record.get("reply", {}).get("parent", {}).get("uri", "")
        return parent.startswith(f"at://{bot_did}/")
    for f in record.get("facets") or []:
        for feat in f.get("features", []):
            if feat.get("$type") == "app.bsky.richtext.facet#mention" and feat.get("did") == bot_did:
                return True
    return False


class Bluesky:
    """The few XRPC calls amebo needs, over plain HTTP with an app password."""

    def __init__(self, service: str, handle: str, app_password: str):
        self.service = service.rstrip("/")
        self.handle = handle
        self.app_password = app_password
        self.http = httpx.AsyncClient(timeout=30)
        self.did = ""
        self._access = ""
        self._refresh = ""

    async def login(self):
        r = await self.http.post(f"{self.service}/xrpc/com.atproto.server.createSession",
                                 json={"identifier": self.handle, "password": self.app_password})
        r.raise_for_status()
        self._session(r.json())

    def _session(self, s: Dict[str, Any]):
        self.did, self._access, self._refresh = s["did"], s["accessJwt"], s["refreshJwt"]

    async def _call(self, method: str, nsid: str, **kw) -> Dict[str, Any]:
        for attempt in (0, 1):
            r = await self.http.request(method, f"{self.service}/xrpc/{nsid}",
                                        headers={"Authorization": f"Bearer {self._access}"}, **kw)
            if r.status_code in (400, 401) and attempt == 0 \
                    and "ExpiredToken" in r.text:
                await self._renew()
                continue
            r.raise_for_status()
            return r.json() if r.content else {}
        raise RuntimeError("unreachable")

    async def _renew(self):
        r = await self.http.post(f"{self.service}/xrpc/com.atproto.server.refreshSession",
                                 headers={"Authorization": f"Bearer {self._refresh}"})
        if r.status_code >= 400:
            await self.login()
        else:
            self._session(r.json())

    async def resolve(self, handle_or_did: str) -> str:
        if handle_or_did.startswith("did:"):
            return handle_or_did
        r = await self._call("GET", "com.atproto.identity.resolveHandle",
                             params={"handle": handle_or_did.lstrip("@")})
        return r["did"]

    async def notifications(self) -> List[Dict[str, Any]]:
        r = await self._call("GET", "app.bsky.notification.listNotifications",
                             params={"limit": 50})
        return r.get("notifications", [])

    async def thread(self, uri: str) -> Dict[str, Any]:
        r = await self._call("GET", "app.bsky.feed.getPostThread",
                             params={"uri": uri, "depth": 0, "parentHeight": 30})
        return r["thread"]

    async def reply(self, text: str, root: Dict[str, str], parent: Dict[str, str]) -> Dict[str, str]:
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reply": {"root": root, "parent": parent},
        }
        facets = link_facets(text)
        if facets:
            record["facets"] = facets
        r = await self._call("POST", "com.atproto.repo.createRecord",
                             json={"repo": self.did, "collection": "app.bsky.feed.post",
                                   "record": record})
        return {"uri": r["uri"], "cid": r["cid"]}


class HandledLog:
    """Notification URIs already dealt with, one per line, appended as they are handled."""

    def __init__(self, path: Path):
        self.path = path
        self.fresh = not path.exists()
        self.seen: Set[str] = set(path.read_text().split()) if not self.fresh else set()

    def __contains__(self, uri: str) -> bool:
        return uri in self.seen

    def add(self, uri: str):
        self.seen.add(uri)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(uri + "\n")


class BlueskyAnswerer(ClaudeMax):
    def __init__(self, client: Bluesky, owners: List[str], state_file: Path, **kwargs):
        super().__init__(**kwargs)
        self.bsky = client
        self.owner_names = owners
        self.owners: Set[str] = set()
        self.handled = HandledLog(state_file)

    def system_prompt_text(self) -> str:
        return system_prompt() + "\n\n" + BLUESKY_PROMPT.read_text().split("\n---\n", 1)[-1].strip()

    async def start(self):
        await self.bsky.login()
        self.owners = {await self.bsky.resolve(o) for o in self.owner_names}
        if not self.owners:
            raise RuntimeError("AMEBO_BLUESKY_OWNERS is empty: amebo would answer no one")
        if self.handled.fresh:
            for n in await self.bsky.notifications():
                self.handled.add(n["uri"])
            logger.info("amebo-bluesky: first run, %d old notifications marked handled",
                        len(self.handled.seen))

    async def poll(self) -> List[str]:
        """Handle every new notification, oldest first. Returns outcomes for the log."""
        outcomes = []
        for n in reversed(await self.bsky.notifications()):
            if n["uri"] in self.handled:
                continue
            outcome = await self.handle(n)
            if not outcome.startswith("wait:"):
                self.handled.add(n["uri"])
            outcomes.append(f"{n['uri']}: {outcome}")
        return outcomes

    async def handle(self, n: Dict[str, Any]) -> str:
        if n.get("reason") not in ("mention", "reply"):
            return f"skip: {n.get('reason')}"
        if n["author"]["did"] not in self.owners:
            return "skip: not an owner"
        if not addresses_bot(n, self.bsky.did):
            return "skip: not addressed to amebo"
        why = scan_text(n.get("record", {}).get("text", ""), self.max_chars)
        if why:
            return f"skip: {why}"
        now = time.time()
        busy = self._not_now(now)
        if busy:
            return f"wait: {busy}"
        self._claims.append(now)

        reply_ref = n.get("record", {}).get("reply")
        root = reply_ref["root"] if reply_ref else {"uri": n["uri"], "cid": n["cid"]}
        parent = {"uri": n["uri"], "cid": n["cid"]}
        lock = self._thread_locks.setdefault(root["uri"], asyncio.Lock())
        async with lock:
            chain = thread_chain(await self.bsky.thread(n["uri"]))
            session = thread_session_id(root["uri"])
            try:
                async with self._slots:
                    answer = await self._ask_claude(session, chain)
            except Exception:
                logger.exception("amebo-bluesky: claude failed on %s", n["uri"])
                await self.bsky.reply("Could not finish this one.", root, parent)
                return "error"
            if not answer.strip():
                return "silent"
            for text in split_reply(answer):
                parent = await self.bsky.reply(text, root, parent)
        return "answered"

    async def _ask_claude(self, session: str, chain: List[Dict[str, Any]]) -> str:
        out = await self._run_claude(["--resume", session],
                                     format_thread(chain[-1:], self.bsky.did), "")
        if out is None:
            out = await self._run_claude(["--session-id", session],
                                         format_thread(chain, self.bsky.did), "")
        if out is None:
            raise RuntimeError("claude did not start a session")
        return out
