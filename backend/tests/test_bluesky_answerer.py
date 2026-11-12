"""amebo on Bluesky: owners only, handled log, thread format, reply splitting."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services import bluesky_answerer as ba

BOT = "did:plc:bot"
OWNER = "did:plc:owner"


def _mention(uri="at://did:plc:owner/app.bsky.feed.post/3a", author=OWNER, text="@amebot do it", reply=None):
    record = {"text": text, "facets": [{"index": {"byteStart": 0, "byteEnd": 7},
              "features": [{"$type": "app.bsky.richtext.facet#mention", "did": BOT}]}]}
    if reply:
        record["reply"] = reply
    return {"uri": uri, "cid": "c1", "reason": "mention", "author": {"did": author, "handle": "owner.bsky.social"},
            "record": record}


def _post(uri, did, handle, text, embed=None):
    p = {"uri": uri, "author": {"did": did, "handle": handle}, "record": {"text": text}}
    if embed:
        p["embed"] = embed
    return p


def _answerer(tmp_path, notifs=(), thread=None):
    client = AsyncMock(spec=ba.Bluesky)
    client.did, client.handle = BOT, "amebot.bsky.social"
    client.notifications.return_value = list(notifs)
    client.thread.return_value = thread or {"post": _post(
        "at://did:plc:owner/app.bsky.feed.post/3a", OWNER, "owner.bsky.social", "@amebot do it")}
    client.reply.side_effect = lambda text, root, parent: {"uri": f"at://{BOT}/p/{len(text)}", "cid": "r"}
    with patch("shutil.which", return_value="/bin/claude"):
        a = ba.BlueskyAnswerer(client, ["owner.bsky.social"], tmp_path / "handled.txt", workdir=str(tmp_path))
    a.owners = {OWNER}
    return a


@pytest.mark.asyncio
async def test_owner_mention_is_answered_and_logged(tmp_path):
    a = _answerer(tmp_path, [_mention()])
    a._run_claude = AsyncMock(side_effect=[None, "Saved. https://example.org/x"])
    out = await a.poll()
    assert out[0].endswith("answered")
    text, root, parent = a.bsky.reply.await_args.args
    assert root == parent == {"uri": "at://did:plc:owner/app.bsky.feed.post/3a", "cid": "c1"}
    assert "at://did:plc:owner/app.bsky.feed.post/3a" in (tmp_path / "handled.txt").read_text()
    assert await a.poll() == []


@pytest.mark.asyncio
async def test_stranger_is_never_answered(tmp_path):
    a = _answerer(tmp_path, [_mention(author="did:plc:stranger")])
    a._run_claude = AsyncMock()
    assert (await a.poll())[0].endswith("skip: not an owner")
    a._run_claude.assert_not_awaited()
    a.bsky.reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_resting_leaves_the_mention_for_later(tmp_path):
    a = _answerer(tmp_path, [_mention()])
    a._not_now = lambda now: "asleep"
    assert (await a.poll())[0].endswith("wait: asleep")
    assert not (tmp_path / "handled.txt").exists()


@pytest.mark.asyncio
async def test_first_run_does_not_answer_old_mentions(tmp_path):
    a = _answerer(tmp_path, [_mention()])
    a.bsky.resolve.return_value = OWNER
    await a.start()
    a._run_claude = AsyncMock()
    assert await a.poll() == []


@pytest.mark.asyncio
async def test_reply_in_thread_keeps_the_root_and_chains_posts(tmp_path):
    root = {"uri": "at://did:plc:x/app.bsky.feed.post/root", "cid": "rc"}
    a = _answerer(tmp_path, [_mention(reply={"root": root, "parent": root})])
    a._run_claude = AsyncMock(return_value="word " * 120)
    await a.poll()
    calls = a.bsky.reply.await_args_list
    assert len(calls) == 2
    assert all(c.args[1] == root for c in calls)
    assert calls[1].args[2]["uri"].startswith(f"at://{BOT}/")


def test_thread_marks_the_request_and_shows_link_cards():
    chain = ba.thread_chain({
        "post": _post("at://o/app.bsky.feed.post/2", OWNER, "owner.bsky.social", "@amebot pull this in"),
        "parent": {"post": _post("at://l/app.bsky.feed.post/1", "did:plc:l", "lawyer.bsky.social", "New law passed",
                                 embed={"external": {"uri": "https://law.example/hb1", "title": "HB1", "description": "d"}})}})
    text = ba.format_thread(chain, BOT)
    assert text.index("New law passed") < text.index("pull this in")
    assert "https://law.example/hb1" in text
    assert 'latest="true">\n@amebot pull this in' in text
    assert "https://bsky.app/profile/lawyer.bsky.social/post/1" in text


def test_split_respects_the_post_limit():
    posts = ba.split_reply("A sentence here. " * 100)
    assert len(posts) == ba.MAX_POSTS
    assert all(len(p) <= ba.POST_LIMIT for p in posts)
    assert posts[-1].endswith("…")


def test_link_facets_use_utf8_byte_offsets():
    text = "Café done: https://example.org/a."
    (f,) = ba.link_facets(text)
    b = text.encode()
    assert b[f["index"]["byteStart"]:f["index"]["byteEnd"]].decode() == "https://example.org/a"


def test_sessions_are_per_thread_root():
    assert ba.thread_session_id("at://a/1") == ba.thread_session_id("at://a/1") != ba.thread_session_id("at://a/2")


def test_reply_to_someone_else_is_not_addressed():
    n = {"reason": "reply", "record": {"reply": {"parent": {"uri": "at://did:plc:other/app.bsky.feed.post/1"}}}}
    assert not ba.addresses_bot(n, BOT)
    n["record"]["reply"]["parent"]["uri"] = f"at://{BOT}/app.bsky.feed.post/1"
    assert ba.addresses_bot(n, BOT)


def test_prompt_adds_the_bluesky_section():
    with patch("shutil.which", return_value="/bin/claude"):
        a = ba.BlueskyAnswerer(AsyncMock(), [], __import__("pathlib").Path("/nonexistent/h"), workdir="/tmp")
    p = a.system_prompt_text()
    assert "In Slack, from Claude Code" in p and "On Bluesky, from Claude Code" in p
    assert "# amebo on Bluesky" not in p
