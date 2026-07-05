'use client';

import { KeyLinksBar } from '@/src/components/dashboard/KeyLinksBar';
import { CampaignsBoard } from '@/src/components/dashboard/CampaignsBoard';

/**
 * Dashboard v1 — an ORIENTATION surface, not a workspace. Read-only: pills
 * (the org's tools) and campaign cards, every element linking out to the tool
 * that owns the thing. No edit-in-place, no assembled mutable views.
 *
 * Standing principle (docs/DASHBOARD.md): everything visible is relevant to
 * the team — no headings over self-explanatory elements, no cruft words.
 * The conversations list lives in the chat view only.
 *
 * Sections render ONLY when they have real content — never a blank placeholder.
 */
export default function DashboardPage() {
  return (
    <div className="min-w-0">
      <h1 className="sr-only">Dashboard</h1>
      <KeyLinksBar />
      <CampaignsBoard />
    </div>
  );
}
