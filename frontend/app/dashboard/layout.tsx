'use client';

import { ProtectedRoute } from '@/src/components/auth/ProtectedRoute';
import { CohortNav } from '@/src/components/CohortNav';
import { AmeboNav } from '@/src/components/AmeboNav';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedRoute>
      <CohortNav />
      <div className="min-h-screen bg-gray-50">
        <AmeboNav />
        <main className="max-w-7xl mx-auto py-4 px-4 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </ProtectedRoute>
  );
}
