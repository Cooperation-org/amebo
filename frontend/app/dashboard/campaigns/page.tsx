'use client';

import { CampaignsBoard } from '@/src/components/dashboard/CampaignsBoard';

/**
 * The campaigns board — one card per live campaign, read from the org's own
 * context repo, every card linking out to the tool that owns the thing
 * (docs/DASHBOARD.md v1). Read-only.
 *
 * It used to be the dashboard home, under a row of links to Tasks, CRM and
 * governance. Those links moved out to the top navbar, where the cohort's
 * other apps already sit, and the home became the inbox (golda 2026-08-10),
 * so the board keeps an address of its own.
 *
 * Renders only when the org has real campaigns; an org with no context repo
 * gets nothing, never a blank placeholder.
 */
export default function CampaignsPage() {
  return (
    <div className="min-w-0">
      <h1 className="sr-only">Campaigns</h1>
      <CampaignsBoard />
    </div>
  );
}
