'use client';

import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/src/store/useAuthStore';
import { SlackWorkspaceForm } from '@/src/components/onboarding/SlackWorkspaceForm';
import { ProtectedRoute } from '@/src/components/auth/ProtectedRoute';

export default function OnboardingPage() {
  const router = useRouter();
  const { user } = useAuthStore();

  const handleSuccess = () => {
    router.push('/dashboard');
  };

  const handleSkip = () => {
    router.push('/dashboard');
  };

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-gray-50 flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-2xl w-full space-y-8">
          <div className="text-center">
            <h1 className="text-3xl font-bold text-gray-900">
              Welcome to Slack Helper Bot!
            </h1>
            <p className="mt-2 text-gray-600">
              Hi {user?.email}, let's get your workspace connected.
            </p>
          </div>
          
          <SlackWorkspaceForm 
            onSuccess={handleSuccess}
            onSkip={handleSkip}
          />
        </div>
      </div>
    </ProtectedRoute>
  );
}