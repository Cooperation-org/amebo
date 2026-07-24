"""
Trigger the cohort VM's earnkit runner to provision a new team's full stack.

When org provisioning learns about a brand-new org from a GovKit founder accept
(source 'govkit-accept', org row created), the GovKit org already exists but the
rest of the team stack — Odoo CRM database, Taiga project, amebo instance row,
Caddy route — does not. earnkit's add-team.yml creates all of it, and the
earnkit-runner service (same VM, localhost-only, bearer token) executes that
playbook on request. This module is amebo's client for it.

Policy note (golda, 2026-07-20): org creation is DELIBERATE. This fires only for
orgs GovKit itself created from a founder invite naming a real venture (or a
future explicitly-approved flow, e.g. an ideas-page kickoff routed through the
same provision endpoint). Pool/applicant accepts never create an org and never
reach this code.

Fire-and-forget like GovKit's own reporter: a runner failure must never fail the
provision request. The runner keeps a job log; failures are visible there and in
our warning logs. No-op when TEAM_RUNNER_URL / TEAM_RUNNER_TOKEN are unset.
"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

# The runner answers immediately (it queues the job and runs the playbook in the
# background), so a short timeout only guards against the service being wedged.
TIMEOUT_SECONDS = 5


def trigger_add_team(slug: str, name: str) -> None:
    """
    Ask the earnkit runner to run add-team for org `slug` / display `name`.

    Never raises. No-op (debug log) when TEAM_RUNNER_URL / TEAM_RUNNER_TOKEN are
    unset — deployments without a runner (non-cohort) simply skip provisioning.
    """
    base_url = os.environ.get("TEAM_RUNNER_URL") or ""
    token = os.environ.get("TEAM_RUNNER_TOKEN") or ""
    if not base_url or not token:
        logger.debug(
            "team stack runner skipped (TEAM_RUNNER_URL/TEAM_RUNNER_TOKEN unset): %s", slug
        )
        return
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/run/add-team",
            json={"team_slug": slug, "team_name": name},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code == 202:
            logger.info(
                "team stack queued for org %s (runner job %s)",
                slug,
                response.json().get("job_id", "?"),
            )
        else:
            logger.warning(
                "team stack runner refused org %s: HTTP %s %s — provision unaffected; "
                "run add-team.yml by hand or re-trigger",
                slug,
                response.status_code,
                response.text[:500],
            )
    except Exception:
        logger.warning(
            "team stack runner unreachable for org %s — provision unaffected; "
            "run add-team.yml by hand or re-trigger",
            slug,
            exc_info=True,
        )


def sync_members(slug: str) -> None:
    """Ask the earnkit runner to reconcile org `slug`'s CRM + Taiga membership now.

    This is a latency optimization on invite accept: the earnkit-sync-members
    timer already provisions every member org-wide every ~5 min, so this only
    makes the accepting member land in Odoo + Taiga within seconds instead of
    waiting for the next tick. It is NEVER the source of truth — a failure here
    is covered by that timer.

    Same contract/return shape as trigger_add_team: never raises, no-op (debug
    log) when TEAM_RUNNER_URL / TEAM_RUNNER_TOKEN are unset. HTTP 409 means a
    sync for this slug is already queued/running and the runner coalesced ours
    into it — that is success, not a failure.
    """
    base_url = os.environ.get("TEAM_RUNNER_URL") or ""
    token = os.environ.get("TEAM_RUNNER_TOKEN") or ""
    if not base_url or not token:
        logger.debug(
            "member sync skipped (TEAM_RUNNER_URL/TEAM_RUNNER_TOKEN unset): %s", slug
        )
        return
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/run/sync-members",
            json={"team_slug": slug},
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code == 202:
            logger.info(
                "member sync queued for org %s (runner job %s)",
                slug,
                response.json().get("job_id", "?"),
            )
        elif response.status_code == 409:
            # A sync for this slug is already in flight; the runner folded ours
            # into it. Nothing missed — this is the coalesced-success path.
            logger.info(
                "member sync for org %s coalesced into an in-flight run (HTTP 409)",
                slug,
            )
        else:
            logger.warning(
                "member sync runner refused org %s: HTTP %s %s — provision "
                "unaffected; the sync-members timer will reconcile on its next tick",
                slug,
                response.status_code,
                response.text[:500],
            )
    except Exception:
        logger.warning(
            "member sync runner unreachable for org %s — provision unaffected; "
            "the sync-members timer will reconcile on its next tick",
            slug,
            exc_info=True,
        )
