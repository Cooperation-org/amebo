"""
WP2 tests: OrgResolver precedence chain (arch §4.2) with fake repos (pure, no
DB), plus real-DB smoke tests for the new recognition/routing repos.
"""

from __future__ import annotations

import uuid

import pytest

from src.services.org_context import OrgContext, Venue, MissingOrgContext
from src.services.org_resolution import OrgResolver


# --- fakes ------------------------------------------------------------------

class FakeMembers:
    def __init__(self, m):
        self.m = m  # {person_id: [org_id, ...]}

    def memberships(self, pid):
        return [{"org_id": o} for o in self.m.get(pid, [])]


class FakeInstances:
    def __init__(self, served):
        self.served = served  # {instance_id: [org_id, ...]}

    def orgs_for_instance(self, iid):
        return list(self.served.get(iid, []))


ORG_META = {
    1: {"org_id": 1, "slug": "rtv", "name": "Raise the Voices",
        "aliases": ["rtv", "raise the voices"]},
    2: {"org_id": 2, "slug": "civicworks", "name": "CivicWorks", "aliases": ["cw"]},
    3: {"org_id": 3, "slug": "linkedtrust", "name": "LinkedTrust", "aliases": []},
}


class FakeOrgs:
    def metadata(self, ids):
        return [ORG_META[i] for i in ids if i in ORG_META]


class FakeRouting:
    def __init__(self, channel=None, workspace=None, pins=None):
        self.channel = channel or {}
        self.workspace = workspace or {}
        self.pins = dict(pins or {})
        self.pinned = []

    def thread_pin(self, tref):
        return self.pins.get(tref)

    def channel_default(self, ws, ch):
        return self.channel.get((ws, ch))

    def workspace_default(self, ws):
        return self.workspace.get(ws)

    def pin_thread(self, tref, oid, by=None):
        self.pinned.append((tref, oid, by))
        self.pins[tref] = oid


class FakeIdentity:
    def __init__(self, m):
        self.m = m  # {(provider, context_ref, external_id): person_id}

    def recognize(self, provider, external_id, context_ref=""):
        return self.m.get((provider, context_ref, external_id))


def _resolver(members, served, routing=None, identity=None):
    return OrgResolver(
        member_repo=FakeMembers(members),
        instance_repo=FakeInstances(served),
        org_repo=FakeOrgs(),
        routing_repo=routing or FakeRouting(),
        identity_repo=identity or FakeIdentity({}),
    )


# --- the chain, rung by rung -------------------------------------------------

class TestResolutionChain:
    def test_sole_membership(self):
        r = _resolver({10: [1]}, {99: [1, 2, 3]})
        res = r.resolve(instance_id=99, person_id=10, utterance="hey", venue=None)
        assert res.status == "resolved" and res.org_id == 1 and res.should_pin is False

    def test_explicit_targeting_by_name_pins(self):
        routing = FakeRouting()
        r = _resolver({10: [1, 2]}, {99: [1, 2]}, routing=routing)
        v = Venue(channel_kind="slack", thread_ref="t1")
        res = r.resolve(instance_id=99, person_id=10,
                        utterance="file this under raise the voices please", venue=v)
        assert res.status == "resolved" and res.org_id == 1 and res.should_pin
        assert routing.pinned == [("t1", 1, 10)]  # pinned to the thread

    def test_explicit_targeting_by_alias(self):
        r = _resolver({10: [1, 2]}, {99: [1, 2]})
        res = r.resolve(instance_id=99, person_id=10,
                        utterance="for rtv: remember this", venue=None)
        assert res.org_id == 1

    def test_ambiguous_asks_one_line_with_names(self):
        r = _resolver({10: [1, 2]}, {99: [1, 2]})
        res = r.resolve(instance_id=99, person_id=10, utterance="hello", venue=None)
        assert res.status == "ambiguous"
        assert {c["org_id"] for c in res.candidates} == {1, 2}
        assert "Raise the Voices" in res.message and "CivicWorks" in res.message

    def test_thread_pin_resolves(self):
        routing = FakeRouting(pins={"t9": 2})
        r = _resolver({10: [1, 2]}, {99: [1, 2]}, routing=routing)
        v = Venue(channel_kind="slack", thread_ref="t9")
        res = r.resolve(instance_id=99, person_id=10, utterance="ok", venue=v)
        assert res.status == "resolved" and res.org_id == 2

    def test_explicit_targeting_beats_pin_and_repins(self):
        routing = FakeRouting(pins={"t9": 2})
        r = _resolver({10: [1, 2]}, {99: [1, 2]}, routing=routing)
        v = Venue(channel_kind="slack", thread_ref="t9")
        res = r.resolve(instance_id=99, person_id=10,
                        utterance="actually put this under rtv", venue=v)
        assert res.org_id == 1 and res.should_pin
        assert routing.pins["t9"] == 1  # re-pinned

    def test_channel_default_resolves(self):
        routing = FakeRouting(channel={("T1", "C1"): 2})
        r = _resolver({10: [1, 2]}, {99: [1, 2]}, routing=routing)
        v = Venue(channel_kind="slack", workspace_ref="T1", channel_ref="C1")
        res = r.resolve(instance_id=99, person_id=10, utterance="hi", venue=v)
        assert res.org_id == 2

    def test_workspace_default_fallback(self):
        routing = FakeRouting(workspace={"T1": 1})
        r = _resolver({10: [1, 2]}, {99: [1, 2]}, routing=routing)
        v = Venue(channel_kind="slack", workspace_ref="T1", channel_ref="C-none")
        res = r.resolve(instance_id=99, person_id=10, utterance="hi", venue=v)
        assert res.org_id == 1

    def test_default_ignored_when_not_a_candidate(self):
        # channel default points at org 3, but the person isn't a member -> ask
        routing = FakeRouting(channel={("T1", "C1"): 3})
        r = _resolver({10: [1, 2]}, {99: [1, 2, 3]}, routing=routing)
        v = Venue(channel_kind="slack", workspace_ref="T1", channel_ref="C1")
        res = r.resolve(instance_id=99, person_id=10, utterance="hi", venue=v)
        assert res.status == "ambiguous"

    def test_first_mentioned_org_wins_not_lowest_id(self):
        # Both named; CivicWorks (org 2) appears earlier in the text than RTV
        # (org 1) -> resolve 2, proving position beats id order.
        r = _resolver({10: [1, 2]}, {99: [1, 2]})
        res = r.resolve(instance_id=99, person_id=10,
                        utterance="file under civicworks, or maybe raise the voices",
                        venue=None)
        assert res.status == "resolved" and res.org_id == 2

    def test_member_but_instance_not_serving(self):
        # person is a member of org 1, but this instance serves only 2 and 3
        r = _resolver({10: [1]}, {99: [2, 3]})
        res = r.resolve(instance_id=99, person_id=10,
                        utterance="put this under raise the voices", venue=None)
        assert res.status == "not_served" and "Raise the Voices" in res.message

    def test_naming_a_served_non_member_org(self):
        r = _resolver({10: [1]}, {99: [1, 3]})
        res = r.resolve(instance_id=99, person_id=10,
                        utterance="file under linkedtrust", venue=None)
        assert res.status == "not_member" and "LinkedTrust" in res.message

    def test_no_candidates_is_none(self):
        r = _resolver({10: [1]}, {99: [2, 3]})  # member of 1, instance serves 2,3
        res = r.resolve(instance_id=99, person_id=10, utterance="hi", venue=None)
        assert res.status == "none"

    def test_unrecognized_person_is_none(self):
        r = _resolver({}, {99: [1, 2]})
        res = r.resolve(instance_id=99, person_id=None, utterance="hi", venue=None)
        assert res.status == "none"


class TestRecognitionAndContext:
    def test_recognize_maps_slack_identity_to_person(self):
        ident = FakeIdentity({("slack", "T1", "U123"): 10})
        r = _resolver({}, {}, identity=ident)
        v = Venue(channel_kind="slack", workspace_ref="T1")
        assert r.recognize(v, "U123") == 10
        assert r.recognize(v, "Uxxx") is None

    def test_org_context_for_resolved(self):
        r = _resolver({10: [1]}, {99: [1]})
        res = r.resolve(instance_id=99, person_id=10, utterance="hi", venue=None)
        ctx = r.org_context_for(res, instance_id=99, person_id=10, venue=None)
        assert isinstance(ctx, OrgContext)
        assert ctx.org_id == 1 and ctx.actor_type == "user" and ctx.actor_person_id == 10

    def test_org_context_for_unresolved_is_none(self):
        r = _resolver({10: [1, 2]}, {99: [1, 2]})
        res = r.resolve(instance_id=99, person_id=10, utterance="hi", venue=None)
        assert r.org_context_for(res, instance_id=99, person_id=10, venue=None) is None

    def test_for_goal_is_claw(self):
        r = _resolver({}, {})
        ctx = r.for_goal({"org_id": 7}, instance_id=99)
        assert ctx.org_id == 7 and ctx.actor_type == "claw" and ctx.actor_person_id is None


class TestOrgContextObject:
    def test_rejects_bad_actor_type(self):
        with pytest.raises(ValueError):
            OrgContext(org_id=1, instance_id=1, actor_type="robot")

    def test_missing_org_context_is_runtimeerror(self):
        assert issubclass(MissingOrgContext, RuntimeError)


# --- real-DB smoke tests for the new repos ----------------------------------

from src.db.connection import DatabaseConnection
from src.db.repositories.person_identity_repo import PersonIdentityRepo
from src.db.repositories.org_routing_repo import OrgRoutingRepo
from src.db.repositories.org_repo import OrgRepo


def _uid():
    return uuid.uuid4().hex[:12]


@pytest.fixture
def db_org_and_user():
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug) VALUES (%s, %s) RETURNING org_id",
                ("Recognize Org", f"recognize-{_uid()}"),
            )
            org_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO platform_users (org_id, email, password_hash, full_name, role) "
                "VALUES (%s, %s, 'x', 'R U', 'member') RETURNING user_id",
                (org_id, f"recognize-{_uid()}@example.com"),
            )
            uid = cur.fetchone()[0]
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)
    yield org_id, uid
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM organizations WHERE org_id = %s", (org_id,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


class TestRecognitionRepoRealDB:
    def test_link_and_recognize(self, db_org_and_user):
        _, uid = db_org_and_user
        repo = PersonIdentityRepo()
        repo.link(uid, "slack", f"U{_uid()}", context_ref="TWORK")
        ext = repo.identities_for(uid)[0]["external_id"]
        assert repo.recognize("slack", ext, "TWORK") == uid
        assert repo.recognize("slack", ext, "OTHER") is None

    def test_aliases_roundtrip(self, db_org_and_user):
        org_id, _ = db_org_and_user
        OrgRepo().set_aliases(org_id, ["foo", "bar"])
        assert OrgRepo().get(org_id)["aliases"] == ["foo", "bar"]

    def test_channel_default_and_pin(self, db_org_and_user):
        org_id, uid = db_org_and_user
        routing = OrgRoutingRepo()
        tref = f"thread-{_uid()}"
        routing.pin_thread(tref, org_id, uid)
        assert routing.thread_pin(tref) == org_id
        # clean up the pin (no cascade from org for a bare thread_ref delete)
        conn = DatabaseConnection.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM conversation_org_pins WHERE thread_ref = %s", (tref,))
                conn.commit()
        finally:
            DatabaseConnection.return_connection(conn)
