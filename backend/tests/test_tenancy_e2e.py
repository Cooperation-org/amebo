"""
End-to-end tenancy test (WP1 + WP2): REAL repos + REAL OrgResolver + REAL trust
gate + REAL tool executor, against the live amebo DB. No fakes.

Seeds a realistic world — two orgs, a person who belongs to both, one instance
serving both, a Slack identity, a channel default — then drives the full path
your driving story needs:

  recognize speaker -> resolve target org (explicit "file under X", thread pin,
  channel default) -> build OrgContext -> execute a tool under it with the trust
  gate enforced. Plus the negative (unknown speaker refused) and the goal/claw
  path.
"""

from __future__ import annotations

import uuid

import pytest

from src.db.connection import DatabaseConnection
from src.db.repositories.org_member_repo import OrgMemberRepo
from src.db.repositories.instance_repo import InstanceRepo
from src.db.repositories.org_repo import OrgRepo
from src.db.repositories.org_routing_repo import OrgRoutingRepo
from src.db.repositories.person_identity_repo import PersonIdentityRepo
from src.services.org_resolution import OrgResolver
from src.services.org_context import OrgContext
from src.services.trust import Principal
from src.tools import registry
from src.tools.registry import Tool, execute_tool


def _uid():
    return uuid.uuid4().hex[:10]


# Two real tools registered once for the executor leg of the e2e.
_RAN = {}


def _make_tool(name, is_read_only=True, access_class=None):
    def _run(tool_input, context):
        _RAN[name] = context
        return f"ran:{context.get('org_id')}"
    registry.register_tool(Tool(
        name=name, description="e2e", input_schema={"type": "object"},
        execute=_run, is_read_only=is_read_only, access_class=access_class,
    ))


_make_tool("e2e_note", is_read_only=False)          # write-class
_make_tool("e2e_admin", is_read_only=False, access_class="admin")


@pytest.fixture
def world():
    """Seed orgs RTV+CW, a person in both, an instance serving both, a Slack
    identity + workspace + channel default. Returns a namespace of ids. Cleaned
    up by cascading org/instance/workspace deletes."""
    slug = _uid()
    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, aliases) "
                "VALUES (%s, %s, %s::jsonb) RETURNING org_id",
                ("Raise the Voices E2E", f"rtv-{slug}", '["rtv-e2e"]'),
            )
            rtv = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO organizations (org_name, org_slug, aliases) "
                "VALUES (%s, %s, %s::jsonb) RETURNING org_id",
                ("CivicWorks E2E", f"cw-{slug}", '["cw-e2e"]'),
            )
            cw = cur.fetchone()[0]
            # person lives in RTV (trigger mirrors -> org_members RTV)
            cur.execute(
                "INSERT INTO platform_users (org_id, email, password_hash, full_name, role) "
                "VALUES (%s, %s, 'x', 'E2E Person', 'member') RETURNING user_id",
                (rtv, f"e2e-{slug}@example.com"),
            )
            person = cur.fetchone()[0]
            # workspace for the channel default / slack venue
            ws = f"T{slug[:8]}"
            cur.execute(
                "INSERT INTO workspaces (workspace_id, team_name) VALUES (%s, %s)",
                (ws, "E2E Team"),
            )
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)

    # membership + instance-serving via the real repos
    OrgMemberRepo().add_member(cw, person)                 # now a member of both
    inst = InstanceRepo().create(name="E2E Inst", slug=f"e2e-{slug}", org_id=rtv)["id"]
    InstanceRepo().add_org(inst, cw)                       # instance serves both
    PersonIdentityRepo().link(person, "slack", f"U{slug}", context_ref=ws)
    channel = f"C{slug[:8]}"
    OrgRoutingRepo().set_channel_default(ws, channel, rtv)  # channel defaults to RTV

    ns = dict(rtv=rtv, cw=cw, person=person, inst=inst, ws=ws, channel=channel,
              slack_id=f"U{slug}")
    yield ns

    conn = DatabaseConnection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM instances WHERE id = %s", (inst,))
            cur.execute("DELETE FROM organizations WHERE org_id = ANY(%s)", ([rtv, cw],))
            cur.execute("DELETE FROM workspaces WHERE workspace_id = %s", (ws,))
            conn.commit()
    finally:
        DatabaseConnection.return_connection(conn)


from src.services.org_context import Venue


def test_e2e_recognize_resolve_execute(world):
    r = OrgResolver()
    ws, ch, slack_id = world["ws"], world["channel"], world["slack_id"]

    # 1. recognition: the Slack identity maps to our person
    venue = Venue(channel_kind="slack", workspace_ref=ws, channel_ref=ch, thread_ref="thread-A")
    person_id = r.recognize(venue, slack_id)
    assert person_id == world["person"]

    # 2. explicit targeting: "file under cw-e2e" -> CivicWorks, and it pins
    res = r.resolve(instance_id=world["inst"], person_id=person_id,
                    utterance="please file this under cw-e2e", venue=venue)
    assert res.status == "resolved" and res.org_id == world["cw"] and res.should_pin
    assert OrgRoutingRepo().thread_pin("thread-A") == world["cw"]  # persisted

    # 3. build OrgContext + execute a write tool under it, T1 principal, gate passes
    ctx = r.org_context_for(res, instance_id=world["inst"], person_id=person_id, venue=venue)
    assert isinstance(ctx, OrgContext) and ctx.org_id == world["cw"]
    t1 = Principal(transport="slack", person_id=person_id, channel_verified=True)
    out = execute_tool("e2e_note", {}, org_context=ctx, principal=t1)
    assert out == f"ran:{world['cw']}"
    assert _RAN["e2e_note"]["org_id"] == world["cw"]

    # 4. neutral follow-up in the SAME thread -> still CW via the pin
    res2 = r.resolve(instance_id=world["inst"], person_id=person_id,
                     utterance="thanks, add a note", venue=venue)
    assert res2.status == "resolved" and res2.org_id == world["cw"]

    # 5. neutral message in a FRESH thread in the channel -> RTV via channel default
    venue_b = Venue(channel_kind="slack", workspace_ref=ws, channel_ref=ch, thread_ref="thread-B")
    res3 = r.resolve(instance_id=world["inst"], person_id=person_id,
                     utterance="hi there", venue=venue_b)
    assert res3.status == "resolved" and res3.org_id == world["rtv"]


def test_e2e_unknown_speaker_gets_no_org_and_write_is_refused(world):
    r = OrgResolver()
    venue = Venue(channel_kind="slack", workspace_ref=world["ws"], channel_ref=world["channel"])

    # unknown slack id -> no person -> no candidate org (fail-closed)
    assert r.recognize(venue, "U-NOBODY") is None
    res = r.resolve(instance_id=world["inst"], person_id=None, utterance="do a thing", venue=venue)
    assert res.status == "none"
    assert r.org_context_for(res, instance_id=world["inst"], person_id=None, venue=venue) is None

    # and a T0 principal is refused at the gate — the tool never runs
    _RAN.pop("e2e_note", None)
    t0 = Principal(transport="slack", person_id=None)
    out = execute_tool("e2e_note", {}, principal=t0)
    assert out.startswith("Refused:")
    assert "e2e_note" not in _RAN


def test_e2e_goal_claw_path(world):
    r = OrgResolver()
    ctx = r.for_goal({"org_id": world["rtv"]}, instance_id=world["inst"])
    assert ctx.actor_type == "claw" and ctx.org_id == world["rtv"]
    # service authority passes even the admin gate
    svc = Principal(transport="system", is_service=True)
    out = execute_tool("e2e_admin", {}, org_context=ctx, principal=svc)
    assert out == f"ran:{world['rtv']}"
