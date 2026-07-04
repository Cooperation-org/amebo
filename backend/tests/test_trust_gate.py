"""
WP2 tests: the trust scoring seam (arch §4.3) and the executor gate (I10).
The scorer is swappable; the gate is code below the model. No DB.
"""

from __future__ import annotations

import pytest

from src.services.trust import (
    Principal, TrustLevel, TransportTierEvaluator, required_level,
    evaluate, get_trust_evaluator, set_trust_evaluator,
)
from src.services import trust as trust_mod
from src.services.org_context import OrgContext, Venue, MissingOrgContext
from src.tools import registry
from src.tools.registry import Tool, execute_tool, trust_gate, require_org_context


# --- the default transport->tier evaluator ----------------------------------

class TestTransportTierEvaluator:
    def setup_method(self):
        self.ev = TransportTierEvaluator()

    def test_unknown_speaker_is_t0(self):
        assert self.ev.evaluate(Principal(transport="slack", person_id=None)) == TrustLevel.T0

    def test_slack_verified_member_is_t1(self):
        p = Principal(transport="slack", person_id=5, channel_verified=True)
        assert self.ev.evaluate(p) == TrustLevel.T1

    def test_web_oidc_is_t2(self):
        p = Principal(transport="web", person_id=5, authenticated=True)
        assert self.ev.evaluate(p) == TrustLevel.T2

    def test_email_is_always_t0_even_if_recognized(self):
        # From: is spoofable — email can inform but never authorize (arch §4.3).
        p = Principal(transport="email", person_id=5, authenticated=True,
                      channel_verified=True)
        assert self.ev.evaluate(p) == TrustLevel.T0

    def test_service_actor_is_service(self):
        assert self.ev.evaluate(Principal(transport="system", is_service=True)) == TrustLevel.SERVICE

    def test_required_level_by_access_class(self):
        assert required_level("read") == TrustLevel.T1
        assert required_level("write") == TrustLevel.T1
        assert required_level("admin") == TrustLevel.T2
        assert required_level("bogus") == TrustLevel.T2  # unknown -> fail closed


class TestSwappableSeam:
    def teardown_method(self):
        # restore the default scorer for other tests
        set_trust_evaluator(TransportTierEvaluator())

    def test_evaluator_can_be_replaced_without_touching_gate(self):
        class AlwaysT2:
            def evaluate(self, principal):
                return TrustLevel.T2
        set_trust_evaluator(AlwaysT2())
        assert evaluate(Principal(transport="email")) == TrustLevel.T2  # would be T0 by default
        assert get_trust_evaluator().__class__.__name__ == "AlwaysT2"


# --- the executor gate ------------------------------------------------------

def _register(name, is_read_only=True, access_class=None):
    executed = {"ran": False}

    def _run(tool_input, context):
        executed["ran"] = True
        executed["context"] = context
        return "ok"

    registry.register_tool(Tool(
        name=name, description="t", input_schema={"type": "object"},
        execute=_run, is_read_only=is_read_only, access_class=access_class,
    ))
    return executed


class TestExecutorGate:
    def test_read_tool_refused_at_t0_and_does_not_run(self):
        ex = _register("t_read_gate")
        p = Principal(transport="slack", person_id=None)  # T0
        out = execute_tool("t_read_gate", {}, principal=p)
        assert out.startswith("Refused:") and ex["ran"] is False

    def test_write_tool_allowed_at_t1(self):
        ex = _register("t_write_gate", is_read_only=False)
        p = Principal(transport="slack", person_id=9, channel_verified=True)  # T1
        assert execute_tool("t_write_gate", {}, principal=p) == "ok"
        assert ex["ran"] is True

    def test_admin_tool_refused_at_t1_allowed_at_t2(self):
        _register("t_admin_gate", is_read_only=False, access_class="admin")
        t1 = Principal(transport="slack", person_id=9, channel_verified=True)
        t2 = Principal(transport="web", person_id=9, authenticated=True)
        assert execute_tool("t_admin_gate", {}, principal=t1).startswith("Refused:")
        assert execute_tool("t_admin_gate", {}, principal=t2) == "ok"

    def test_service_actor_passes_gate(self):
        ex = _register("t_service_gate", is_read_only=False, access_class="admin")
        svc = Principal(transport="system", is_service=True)
        assert execute_tool("t_service_gate", {}, principal=svc) == "ok"
        assert ex["ran"] is True

    def test_legacy_call_without_principal_still_runs(self):
        ex = _register("t_legacy_gate", is_read_only=False)
        assert execute_tool("t_legacy_gate", {}, workspace_id="W", org_id=1) == "ok"
        assert ex["ran"] is True

    def test_org_context_threads_org_id_into_context(self):
        ex = _register("t_ctx_gate")
        ctx = OrgContext(org_id=42, instance_id=1, actor_type="user",
                         venue=Venue(channel_kind="slack", workspace_ref="TW"))
        execute_tool("t_ctx_gate", {}, org_context=ctx)
        assert ex["context"]["org_id"] == 42
        assert ex["context"]["workspace_id"] == "TW"
        assert ex["context"]["org_context"] is ctx


class TestRequireOrgContext:
    def test_none_raises(self):
        with pytest.raises(MissingOrgContext):
            require_org_context(None)

    def test_present_returns_it(self):
        ctx = OrgContext(org_id=1, instance_id=1, actor_type="claw")
        assert require_org_context(ctx) is ctx
