'use client';

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Plus, Loader2, CheckCircle, XCircle } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { apiClient } from '@/src/lib/api';

const workspaceSchema = z.object({
  team_name: z.string().min(1, 'Workspace name is required'),
  bot_token: z.string().regex(/^xoxb-/, 'Bot token must start with xoxb-'),
  app_token: z.string().regex(/^xapp-/, 'App token must start with xapp-'),
  signing_secret: z.string().min(32, 'Signing secret must be at least 32 characters'),
});

type WorkspaceFormData = z.infer<typeof workspaceSchema>;

interface AddWorkspaceModalProps {
  onWorkspaceAdded?: () => void;
}

export function AddWorkspaceModal({ onWorkspaceAdded }: AddWorkspaceModalProps) {
  const [open, setOpen] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
    getValues,
  } = useForm<WorkspaceFormData>({
    resolver: zodResolver(workspaceSchema),
  });

  const testConnection = async () => {
    const values = getValues();
    setIsTestingConnection(true);
    setConnectionStatus('idle');

    try {
      await apiClient.testWorkspaceConnection('', {
        bot_token: values.bot_token,
        app_token: values.app_token,
        signing_secret: values.signing_secret,
      });
      setConnectionStatus('success');
    } catch (error) {
      setConnectionStatus('error');
    } finally {
      setIsTestingConnection(false);
    }
  };

  const onSubmit = async (data: WorkspaceFormData) => {
    setIsSubmitting(true);
    try {
      const response = await apiClient.addWorkspace({
        workspace_name: data.team_name,
        bot_token: data.bot_token,
        app_token: data.app_token,
        signing_secret: data.signing_secret,
      });
      
      // Trigger initial backfill for the new workspace
      if (response.workspace_id) {
        try {
          await apiClient.triggerWorkspaceSync(response.workspace_id);
        } catch (backfillError) {
          console.warn('Failed to trigger initial backfill:', backfillError);
        }
      }
      
      onWorkspaceAdded?.();
      setOpen(false);
      reset();
      setConnectionStatus('idle');
    } catch (error) {
      console.error('Failed to add workspace:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    setOpen(false);
    reset();
    setConnectionStatus('idle');
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="h-4 w-4 mr-2" />
          Add Workspace
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add Slack Workspace</DialogTitle>
        </DialogHeader>
        
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="team_name">Workspace Name</Label>
            <Input
              id="team_name"
              placeholder="My Company Workspace"
              {...register('team_name')}
            />
            {errors.team_name && (
              <p className="text-sm text-red-600">{errors.team_name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bot_token">Bot Token</Label>
            <Input
              id="bot_token"
              type="password"
              placeholder="xoxb-..."
              {...register('bot_token')}
            />
            {errors.bot_token && (
              <p className="text-sm text-red-600">{errors.bot_token.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="app_token">App Token</Label>
            <Input
              id="app_token"
              type="password"
              placeholder="xapp-..."
              {...register('app_token')}
            />
            {errors.app_token && (
              <p className="text-sm text-red-600">{errors.app_token.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="signing_secret">Signing Secret</Label>
            <Input
              id="signing_secret"
              type="password"
              placeholder="Your signing secret"
              {...register('signing_secret')}
            />
            {errors.signing_secret && (
              <p className="text-sm text-red-600">{errors.signing_secret.message}</p>
            )}
          </div>

          {/* Connection Test */}
          <Card className="bg-gray-50">
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {connectionStatus === 'success' && (
                    <>
                      <CheckCircle className="h-4 w-4 text-green-600" />
                      <span className="text-sm text-green-600">Connection successful!</span>
                    </>
                  )}
                  {connectionStatus === 'error' && (
                    <>
                      <XCircle className="h-4 w-4 text-red-600" />
                      <span className="text-sm text-red-600">Connection failed</span>
                    </>
                  )}
                  {connectionStatus === 'idle' && (
                    <span className="text-sm text-gray-600">Test your connection before saving</span>
                  )}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={testConnection}
                  disabled={isTestingConnection}
                >
                  {isTestingConnection ? (
                    <>
                      <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                      Testing...
                    </>
                  ) : (
                    'Test Connection'
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>

          <div className="flex gap-2 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || connectionStatus !== 'success'}
              className="flex-1"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Adding...
                </>
              ) : (
                'Add Workspace'
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}