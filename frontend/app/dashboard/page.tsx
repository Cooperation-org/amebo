'use client';

import { useAuthStore } from '@/src/store/useAuthStore';
import { KeyLinksBar } from '@/src/components/dashboard/KeyLinksBar';
import { CampaignsBoard } from '@/src/components/dashboard/CampaignsBoard';
import { ChatListSidebar } from '@/src/components/dashboard/ChatListSidebar';

/**
 * Dashboard v1 — an ORIENTATION surface, not a workspace. Read-only: it shows
 * the org's tools, campaigns, and the user's conversations, and every element
 * links out to the tool that owns the thing. No edit-in-place, no assembled
 * mutable views. Layout: chat-list sidebar · key-links bar on top · campaigns
 * board below.
 *
 * Sections render ONLY when they have real content — never a blank placeholder.
 */
export default function DashboardPage() {
  const { user } = useAuthStore();

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      <ChatListSidebar />

      <div className="flex-1 min-w-0">
        <div className="mb-6">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">
            {user?.org_name || 'Dashboard'}
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Your tools and campaigns — one click to the tool that owns each thing.
          </p>
        </div>

        <KeyLinksBar />
        <CampaignsBoard />
      </div>
    </div>
  );
}
