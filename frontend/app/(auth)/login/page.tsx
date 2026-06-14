'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuthStore } from '@/src/store/useAuthStore';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import Link from 'next/link';
import { loginSchema, type LoginFormData } from '@/src/lib/validations';

export default function LoginPage() {
  const { login, isLoading } = useAuthStore();
  const router = useRouter();

  // Surface errors handed back by the OIDC callback via ?error=.
  useEffect(() => {
    const err = new URLSearchParams(window.location.search).get('error');
    if (!err) return;
    const messages: Record<string, string> = {
      pending_approval: 'Your account is pending approval. An admin will activate it.',
      auth_failed: 'Sign-in failed. Please try again.',
      expired: 'The sign-in request expired. Please try again.',
      state_mismatch: 'Sign-in could not be verified. Please try again.',
      no_email: 'That account has no email address, so we cannot sign you in.',
    };
    toast.error(messages[err] || 'Sign-in error. Please try again.');
    window.history.replaceState(null, '', window.location.pathname);
  }, []);

  const signInWithLinkedTrust = () => {
    const apiBase = process.env.NEXT_PUBLIC_API_URL || '';
    window.location.href = `${apiBase}/api/auth/oidc/login`;
  };

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  });

  const onSubmit = async (data: LoginFormData) => {
    try {
      const result = await login(data.email, data.password);
      toast.success('Login successful!');
      if (result.mustChangePassword) {
        router.push('/set-password');
      } else {
        router.push('/dashboard');
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Login failed');
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold text-center">
            Sign in to Amebo
          </CardTitle>
          <CardDescription className="text-center">
            Enter your email and password to access your account
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={signInWithLinkedTrust}
          >
            Sign in with LinkedTrust
          </Button>
          <p className="mt-2 text-center text-xs text-gray-500">
            Google, Bluesky, or LinkedTrust account
          </p>
          <div className="my-4 flex items-center gap-3 text-xs text-gray-400">
            <span className="h-px flex-1 bg-gray-200" />
            or continue with email
            <span className="h-px flex-1 bg-gray-200" />
          </div>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="Enter your email"
                {...register('email')}
              />
              {errors.email && (
                <p className="text-sm text-red-600">{errors.email.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                {...register('password')}
              />
              {errors.password && (
                <p className="text-sm text-red-600">{errors.password.message}</p>
              )}
            </div>
            <div className="flex justify-end">
              <Link href="/forgot-password" className="text-sm text-blue-600 hover:underline">
                Forgot your password?
              </Link>
            </div>
            <Button
              type="submit" 
              className="w-full" 
              disabled={isLoading}
            >
              {isLoading ? 'Signing in...' : 'Sign in'}
            </Button>
          </form>
          <div className="mt-4 text-center text-sm">
            Don't have an account?{' '}
            <Link href="/signup" className="text-blue-600 hover:underline">
              Sign up
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}