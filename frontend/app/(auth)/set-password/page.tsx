'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuthStore } from '@/src/store/useAuthStore';
import { apiClient } from '@/src/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { changePasswordSchema, type ChangePasswordFormData } from '@/src/lib/validations';
import { Lock, ShieldCheck, Loader2 } from 'lucide-react';

export default function SetPasswordPage() {
  const { isAuthenticated, requiresPasswordChange, clearPasswordChangeRequirement, checkAuth } = useAuthStore();
  const router = useRouter();
  const [hasChecked, setHasChecked] = useState(false);

  // Check auth on mount (restores state from token if page was loaded fresh)
  useEffect(() => {
    checkAuth().finally(() => setHasChecked(true));
  }, [checkAuth]);

  // Redirect once auth check is complete
  useEffect(() => {
    if (!hasChecked) return;

    if (!isAuthenticated) {
      router.push('/login');
    } else if (!requiresPasswordChange) {
      router.push('/dashboard');
    }
  }, [hasChecked, isAuthenticated, requiresPasswordChange, router]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ChangePasswordFormData>({
    resolver: zodResolver(changePasswordSchema),
  });

  const onSubmit = async (data: ChangePasswordFormData) => {
    try {
      await apiClient.changePassword(data.currentPassword, data.newPassword);
      clearPasswordChangeRequirement();
      toast.success('Password set successfully!');
      router.push('/dashboard');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to set password');
    }
  };

  // Show loading while checking auth
  if (!hasChecked) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  // Don't render form if redirecting
  if (!isAuthenticated || !requiresPasswordChange) {
    return null;
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <div className="flex justify-center mb-2">
            <ShieldCheck className="h-12 w-12 text-blue-500" />
          </div>
          <CardTitle className="text-2xl font-bold text-center">
            Welcome! Set your password
          </CardTitle>
          <CardDescription className="text-center">
            You&apos;re logged in with a temporary password. Please set a new password to secure your account.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="currentPassword">Temporary password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
                <Input
                  id="currentPassword"
                  type="password"
                  placeholder="Enter your temporary password"
                  className="pl-10"
                  {...register('currentPassword')}
                />
              </div>
              {errors.currentPassword && (
                <p className="text-sm text-red-600">{errors.currentPassword.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="newPassword">New password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
                <Input
                  id="newPassword"
                  type="password"
                  placeholder="Choose a new password"
                  className="pl-10"
                  {...register('newPassword')}
                />
              </div>
              {errors.newPassword && (
                <p className="text-sm text-red-600">{errors.newPassword.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmNewPassword">Confirm new password</Label>
              <div className="relative">
                <Lock className="absolute left-3 top-3 h-4 w-4 text-gray-400" />
                <Input
                  id="confirmNewPassword"
                  type="password"
                  placeholder="Confirm your new password"
                  className="pl-10"
                  {...register('confirmNewPassword')}
                />
              </div>
              {errors.confirmNewPassword && (
                <p className="text-sm text-red-600">{errors.confirmNewPassword.message}</p>
              )}
            </div>
            <div className="text-xs text-gray-500">
              Password must be at least 8 characters with uppercase, lowercase, and a number.
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Setting password...' : 'Set password & continue'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
