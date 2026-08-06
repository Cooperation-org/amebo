'use client';

// Guard the chat UI behind login, using the same ProtectedRoute the dashboard
// uses. The chat page renders its own full-screen UI, so this layout adds only
// the auth gate and the cohort bar (no nav chrome of its own).
import { ProtectedRoute } from '@/src/components/auth/ProtectedRoute';
import { CohortNav } from '@/src/components/CohortNav';

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <CohortNav />
      {children}
    </ProtectedRoute>
  );
}
