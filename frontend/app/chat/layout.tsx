'use client';

// Guard the chat UI behind login, using the same ProtectedRoute the dashboard
// uses. Chat is the one page that fills the window instead of scrolling, so
// this layout owns the height: the cohort bar takes what it needs and the page
// gets the rest. The page mounts the Amebo bar itself, because chat's own
// controls ride in that bar's right slot.
import { ProtectedRoute } from '@/src/components/auth/ProtectedRoute';
import { CohortNav } from '@/src/components/CohortNav';

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <div className="flex h-[100dvh] flex-col">
        <CohortNav />
        {children}
      </div>
    </ProtectedRoute>
  );
}
