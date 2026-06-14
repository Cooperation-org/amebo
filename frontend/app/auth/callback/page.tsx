'use client';

// OIDC redirect target. The backend (after exchanging the code with the
// LinkedTrust IdP and minting amebo's own session) redirects the browser here
// with the tokens in the URL fragment, e.g.
//   /auth/callback#access_token=...&refresh_token=...
// We stash them via the existing TokenManager and continue to /chat. The
// fragment is stripped from history so tokens don't linger in the URL.
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { TokenManager } from '@/src/lib/auth';
import { toast } from 'sonner';

export default function OidcCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    const hash = window.location.hash.startsWith('#')
      ? window.location.hash.slice(1)
      : '';
    const params = new URLSearchParams(hash);
    const accessToken = params.get('access_token');
    const refreshToken = params.get('refresh_token');

    if (accessToken) {
      TokenManager.setTokens({ access_token: accessToken, token_type: 'bearer', expires_in: 3600 });
      if (refreshToken) TokenManager.setRefreshToken(refreshToken);
      // Drop the fragment from the URL/history before navigating on.
      window.history.replaceState(null, '', window.location.pathname);
      router.replace('/chat');
    } else {
      toast.error('Sign-in did not complete. Please try again.');
      router.replace('/login');
    }
  }, [router]);

  return (
    <div className="min-h-screen flex items-center justify-center text-gray-600">
      Signing you in…
    </div>
  );
}
