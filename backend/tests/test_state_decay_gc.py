"""
Unit tests for State Decay + Per-Store GC.

Pure Python — no database. The real DB-backed policies (ThreadStorePolicy,
GoalEventsPolicy, AbraWorkingMemoryPolicy) have their storage effects exercised
only through paths that do not touch a DB:

  - retention judgment, TTL filtering, registry independence, and the runner's
    keep/decay interposition are tested with in-memory FakePolicy stores;
  - the real policies are tested for their pure logic (is_durable, scope guard)
    and for the abra DRY-RUN path, which by construction issues no DB calls.

This keeps the suite from ever touching the live abra DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services.state_decay.policy import (
    GcPolicy,
    GcReport,
    StoreRegistry,
)
from src.services.state_decay.judgment import (
    default_should_keep,
    should_keep,
    set_retention_judge,
    get_retention_judge,
)
from src.services.state_decay.runner import run_gc
from src.services.state_decay import stores as store_mod


# ---------------------------------------------------------------------------
# In-memory fake store, satisfies the GcPolicy protocol without a DB.
# ---------------------------------------------------------------------------


class FakePolicy:
    """A store backed by an in-memory dict. Items are dicts with at least
    {id, age, durable?, metadata?}. ``age`` is a timedelta of how long ago the
    item was last touched."""

    def __init__(self, name: str, ttl: timedelta, items: list[dict],
                 dry_run: bool = False):
        self._name = name
        self._ttl = ttl
        self._items = {it["id"]: it for it in items}
        self._dry_run = dry_run
        self.expired_calls: list[list] = []  # record what expire() received

    @property
    def name(self) -> str:
        return self._name

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def is_durable(self, item) -> bool:
        return bool(item.get("durable"))

    def enumerate_expirable(self):
        now_age = self._ttl
        for it in self._items.values():
            if it["age"] > now_age and not self.is_durable(it):
                yield it

    def expire(self, items):
        self.expired_calls.append(items)
        if self._dry_run:
            return GcReport(self._name, expired=0, dry_run=True,
                            expired_ids=[it["id"] for it in items])
        for it in items:
            self._items.pop(it["id"], None)
        return GcReport(self._name, expired=len(items),
                        expired_ids=[it["id"] for it in items])

    def remaining_ids(self):
        return set(self._items.keys())


@pytest.fixture(autouse=True)
def reset_judge():
    """Every test starts with the default retention judge."""
    set_retention_judge(default_should_keep)
    yield
    set_retention_judge(default_should_keep)


# ---------------------------------------------------------------------------
# Protocol / registry
# ---------------------------------------------------------------------------


def test_fakepolicy_satisfies_protocol():
    p = FakePolicy("x", timedelta(hours=1), [])
    assert isinstance(p, GcPolicy)


def test_registry_rejects_duplicate_and_non_policy():
    reg = StoreRegistry()
    reg.register(FakePolicy("dup", timedelta(hours=1), []))
    with pytest.raises(ValueError):
        reg.register(FakePolicy("dup", timedelta(hours=1), []))
    with pytest.raises(TypeError):
        reg.register(object())  # not a GcPolicy


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


def test_ttl_expiry_old_items_decay_fresh_survive():
    reg = StoreRegistry()
    p = FakePolicy(
        "ttl",
        ttl=timedelta(hours=24),
        items=[
            {"id": "old", "age": timedelta(hours=48)},
            {"id": "fresh", "age": timedelta(hours=1)},
        ],
    )
    reg.register(p)
    reports = run_gc(reg)
    assert len(reports) == 1
    assert reports[0].expired == 1
    assert p.remaining_ids() == {"fresh"}


# ---------------------------------------------------------------------------
# Kept items survive
# ---------------------------------------------------------------------------


def test_store_durable_items_survive():
    reg = StoreRegistry()
    p = FakePolicy(
        "durable",
        ttl=timedelta(hours=24),
        items=[
            {"id": "keep", "age": timedelta(hours=99), "durable": True},
            {"id": "drop", "age": timedelta(hours=99)},
        ],
    )
    reg.register(p)
    run_gc(reg)
    assert p.remaining_ids() == {"keep"}


def test_metadata_keep_flag_survives_via_default_judge():
    reg = StoreRegistry()
    p = FakePolicy(
        "metakeep",
        ttl=timedelta(hours=24),
        items=[
            {"id": "pinned", "age": timedelta(hours=99), "metadata": {"pin": True}},
            {"id": "ordinary", "age": timedelta(hours=99)},
        ],
    )
    reg.register(p)
    reports = run_gc(reg)
    assert p.remaining_ids() == {"pinned"}
    assert reports[0].kept == 1
    assert reports[0].expired == 1


# ---------------------------------------------------------------------------
# Retention-judgment hook respected
# ---------------------------------------------------------------------------


def test_default_should_keep_heuristic():
    assert default_should_keep({"id": 1}, store="s") is False
    assert default_should_keep({"id": 1, "kept": True}, store="s") is True
    assert default_should_keep(
        {"id": 1, "metadata": {"crystallized": True}}, store="s"
    ) is True
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert default_should_keep({"id": 1, "retained_until": future}, store="s") is True


def test_custom_judge_is_respected():
    # Judge that keeps everything → nothing decays.
    set_retention_judge(lambda item, *, store: True)
    reg = StoreRegistry()
    p = FakePolicy("j", timedelta(hours=1),
                   [{"id": "a", "age": timedelta(hours=99)}])
    reg.register(p)
    run_gc(reg)
    assert p.remaining_ids() == {"a"}

    # Judge that keeps nothing → old item decays.
    set_retention_judge(lambda item, *, store: False)
    p2 = FakePolicy("j2", timedelta(hours=1),
                    [{"id": "a", "age": timedelta(hours=99)}])
    reg2 = StoreRegistry()
    reg2.register(p2)
    run_gc(reg2)
    assert p2.remaining_ids() == set()


def test_judge_failure_is_fail_safe_keep():
    def boom(item, *, store):
        raise RuntimeError("judge exploded")

    set_retention_judge(boom)
    # should_keep swallows the exception and votes KEEP.
    assert should_keep({"id": 1}, store="s") is True
    assert get_retention_judge() is boom


def test_judge_receives_store_name():
    seen = {}

    def record(item, *, store):
        seen["store"] = store
        return False

    set_retention_judge(record)
    reg = StoreRegistry()
    reg.register(FakePolicy("named_store", timedelta(hours=1),
                            [{"id": "x", "age": timedelta(hours=99)}]))
    run_gc(reg)
    assert seen["store"] == "named_store"


# ---------------------------------------------------------------------------
# Per-store policies are independent
# ---------------------------------------------------------------------------


def test_per_store_policies_independent():
    reg = StoreRegistry()
    short = FakePolicy("short", timedelta(hours=1),
                       [{"id": "s1", "age": timedelta(hours=2)}])
    long = FakePolicy("long", timedelta(days=400),
                      [{"id": "l1", "age": timedelta(hours=2)}])
    reg.register(short)
    reg.register(long)
    reports = {r.store: r for r in run_gc(reg)}
    # short TTL expires its item; long TTL keeps its (2h < 400d).
    assert short.remaining_ids() == set()
    assert long.remaining_ids() == {"l1"}
    assert reports["short"].expired == 1
    assert reports["long"].expired == 0


def test_only_filter_runs_subset():
    reg = StoreRegistry()
    a = FakePolicy("a", timedelta(hours=1), [{"id": "a1", "age": timedelta(hours=2)}])
    b = FakePolicy("b", timedelta(hours=1), [{"id": "b1", "age": timedelta(hours=2)}])
    reg.register(a)
    reg.register(b)
    reports = run_gc(reg, only=["a"])
    assert [r.store for r in reports] == ["a"]
    assert a.remaining_ids() == set()
    assert b.remaining_ids() == {"b1"}  # untouched


def test_one_store_failure_isolated():
    class Exploding(FakePolicy):
        def enumerate_expirable(self):
            raise RuntimeError("enumerate boom")

    reg = StoreRegistry()
    reg.register(Exploding("boom", timedelta(hours=1), []))
    good = FakePolicy("good", timedelta(hours=1),
                      [{"id": "g", "age": timedelta(hours=99)}])
    reg.register(good)
    reports = {r.store: r for r in run_gc(reg)}
    assert reports["boom"].note == "enumerate failed"
    assert good.remaining_ids() == set()  # good store still ran


# ---------------------------------------------------------------------------
# Real policies: pure logic + abra DRY-RUN (no DB touched)
# ---------------------------------------------------------------------------


def test_thread_policy_is_durable():
    p = store_mod.ThreadStorePolicy()
    future = datetime.now(timezone.utc) + timedelta(days=1)
    past = datetime.now(timezone.utc) - timedelta(days=1)
    assert p.is_durable({"retained_until": future}) is True
    assert p.is_durable({"retained_until": past}) is False
    assert p.is_durable({"retained_until": None}) is False


def test_abra_policy_refuses_durable_scope_at_construction():
    with pytest.raises(ValueError):
        store_mod.AbraWorkingMemoryPolicy(scope=store_mod.DURABLE_HUMAN_SCOPE)


def test_abra_dry_run_lists_but_deletes_nothing():
    # Default policy is dry-run. expire() in dry-run issues NO DB calls; it
    # only logs and reports. We feed it fake candidate rows directly.
    p = store_mod.AbraWorkingMemoryPolicy()  # dry_run=True by default
    fake_rows = [{"id": 101}, {"id": 102}, {"id": 103}]
    report = p.expire(fake_rows)
    assert report.dry_run is True
    assert report.expired == 0
    assert report.considered == 3
    assert set(report.expired_ids) == {101, 102, 103}


def test_goal_events_archival_deletes_nothing_by_default():
    p = store_mod.GoalEventsPolicy()  # allow_delete=False
    fake_rows = [{"id": 1}, {"id": 2}]
    report = p.expire(fake_rows)
    assert report.dry_run is True
    assert report.expired == 0
    assert report.considered == 2


def test_default_registry_registers_three_stores_safely():
    # The live registry should hold the three stores, and the destructive ones
    # default to non-deleting posture.
    from src.services.state_decay import default_registry
    store_mod.register_default_policies()
    names = set(default_registry.names())
    assert {"threads", "goal_events", "abra_working_memory"} <= names
    abra = default_registry.get("abra_working_memory")
    assert abra._dry_run is True
    assert abra._scope == store_mod.AMEBO_WORKING_SCOPE
