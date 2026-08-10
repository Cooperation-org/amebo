'use client';

import { redirect } from 'next/navigation';

/**
 * Amebo opens on the inbox. Golda 2026-08-10: "should be just inbox, go right
 * to inbox, and have goals and chat. that's all."
 *
 * Every way in — login, the OIDC callback, onboarding, the wordmark, the
 * cohort bar — points at /dashboard, so the landing is decided here once.
 *
 * The links row that used to sit here is gone: tasks, CRM and governance
 * belong to the top navbar, and repeating them inside Amebo made two menus of
 * one. The campaigns board it sat above kept its own address,
 * /dashboard/campaigns.
 */
export default function DashboardPage() {
  redirect('/dashboard/list');
}
