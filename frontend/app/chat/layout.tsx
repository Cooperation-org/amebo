'use client';

// Guard the chat UI behind login, using the same ProtectedRoute the dashboard
// uses. The chat page renders its own full-screen UI, so this layout only adds
// the auth gate (no nav chrome).
import { ProtectedRoute } from '@/src/components/auth/ProtectedRoute';

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
