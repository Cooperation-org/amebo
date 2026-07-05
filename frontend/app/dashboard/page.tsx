'use client';

import { useAuthStore } from '@/src/store/useAuthStore';
import { Skeleton } from '@/components/ui/skeleton';
import { KeyLinksBar } from '@/src/components/dashboard/KeyLinksBar';

/**
 * Dashboard v1 — an ORIENTATION surface, not a workspace. Read-only: it shows
 * the org's tools, campaigns, and the user's conversations, and every element
 * links out to the tool that owns the thing. No edit-in-place, no assembled
 * mutable views. Layout: chat-list sidebar · key-links bar on top · campaigns
 * board below. (Sidebar = Step 3, campaigns board = Step 2 — placeholders now.)
 */
export default function DashboardPage() {
  const { user } = useAuthStore();

  return (
    <div className="flex flex-col lg:flex-row gap-6">
      {/* Chat-list sidebar (Step 3). On phones it stacks BELOW the main content
          (order-last); on wide screens it's the left column (lg:order-first). */}
      <aside className="order-last lg:order-first lg:w-64 lg:flex-shrink-0">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
          Conversations
        </h2>
        <div className="space-y-2" aria-hidden>
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </aside>

      {/* Main column: key links on top, campaigns board below */}
      <div className="flex-1 min-w-0">
        <div className="mb-6">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">
            {user?.org_name || 'Dashboard'}
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Your tools, campaigns, and conversations — one click to the tool that owns each thing.
          </p>
        </div>

        <KeyLinksBar />

        {/* Campaigns board (Step 2) */}
        <section aria-label="Campaigns">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
            Campaigns
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4" aria-hidden>
            {[0, 1, 2].map((i) => (
              <div key={i} className="rounded-lg border bg-white p-4 space-y-3">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-6 w-20" />
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
