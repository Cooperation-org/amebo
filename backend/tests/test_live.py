"""The change notice: who hears it, who does not, and what it must survive."""

import asyncio

import pytest

from src.services import live


@pytest.fixture(autouse=True)
def clean():
    live._subscribers.clear()
    yield
    live._subscribers.clear()


@pytest.mark.asyncio
async def test_a_subscriber_hears_its_own_org():
    q = live.subscribe(1)
    live.publish(1)
    assert await asyncio.wait_for(q.get(), 1) == "work-list"


@pytest.mark.asyncio
async def test_another_orgs_change_is_not_yours():
    q = live.subscribe(1)
    live.publish(2)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q.get(), 0.05)


@pytest.mark.asyncio
async def test_every_watcher_of_an_org_is_told():
    """Two tabs, two laptops — one change reaches all of them."""
    a, b = live.subscribe(1), live.subscribe(1)
    live.publish(1)
    assert await asyncio.wait_for(a.get(), 1)
    assert await asyncio.wait_for(b.get(), 1)


@pytest.mark.asyncio
async def test_unsubscribing_leaves_nothing_behind():
    q = live.subscribe(1)
    live.unsubscribe(1, q)
    assert live.subscriber_count(1) == 0
    live.publish(1)                       # must not raise with nobody listening


@pytest.mark.asyncio
async def test_publishing_to_nobody_is_fine():
    live.publish(1)
    live.publish(None)


@pytest.mark.asyncio
async def test_a_stalled_reader_never_holds_up_a_write():
    """The notice carries no content, so dropping one costs nothing — but a
    write blocking on a browser that stopped reading would cost everything."""
    q = live.subscribe(1)
    for _ in range(live._QUEUE_DEPTH + 20):
        live.publish(1)
    await asyncio.sleep(0)   # notices are handed to the loop, not delivered inline
    assert q.qsize() == live._QUEUE_DEPTH


@pytest.mark.asyncio
async def test_a_write_running_off_the_loop_still_notifies():
    """Sync route bodies run in a threadpool. A notice published from there has
    to cross back to the loop the subscriber is waiting on."""
    q = live.subscribe(1)
    await asyncio.to_thread(live.publish, 1)
    assert await asyncio.wait_for(q.get(), 1) == "work-list"


# ------------------------------------------------------- the stream endpoint

@pytest.mark.asyncio
async def test_the_stream_says_hello_then_pushes_a_change():
    """A stream that stays silent until something happens cannot be told from
    one that never connected, so it opens with 'ready'."""
    from src.api.routes.work_list import stream

    response = await stream(client={"auth": "user", "org_id": 1,
                                    "email": "someone@example.org"})
    events = response.body_iterator

    assert await asyncio.wait_for(events.__anext__(), 1) == "event: ready\ndata: {}\n\n"

    # Wait until the generator is actually parked on the queue before
    # publishing, otherwise the notice is delivered to nobody.
    for _ in range(50):
        if live.subscriber_count(1):
            break
        await asyncio.sleep(0.01)
    nxt = asyncio.ensure_future(events.__anext__())
    await asyncio.sleep(0)
    live.publish(1, "work-list")
    got = await asyncio.wait_for(nxt, 1)
    assert got == 'event: changed\ndata: {"what": "work-list"}\n\n'

    await events.aclose()
    assert live.subscriber_count(1) == 0   # closing the tab lets go of the queue


@pytest.mark.asyncio
async def test_a_client_with_no_org_gets_no_stream():
    from fastapi import HTTPException
    from src.api.routes.work_list import stream

    with pytest.raises(HTTPException) as exc:
        await stream(client={"auth": "user"})
    assert exc.value.status_code == 403
