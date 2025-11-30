'use client';

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent } from '@/components/ui/card';
import { Loader2, CheckCircle, XCircle, Eye, EyeOff, Trash2 } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { apiClient } from '@/src/lib/api';

const editWorkspaceSchema = z.object({
  team_name: z.string().min(1, 'Workspace name is required'),
  bot_token: z.string().regex(/^xoxb-/, 'Bot token must start with xoxb-'),
  app_token: z.string().regex(/^xapp-/, 'App token must start with xapp-'),
  signing_secret: z.string().min(32, 'Signing secret must be at least 32 characters'),
});

type EditWorkspaceFormData = z.infer<typeof editWorkspaceSchema>;

interface Workspace {
  workspace_id: string;
  team_name: string;
  team_domain?: string;
  icon_url?: string;
  is_active: boolean;
  installed_at: string;
  last_active?: string;
  status?: string;
  message_count?: number;
  channel_count?: number;
  last_sync_at?: string;
}

interface EditWorkspaceModalProps {
  workspace: Workspace | null;
  open: boolean;
  onClose: () => void;
  onWorkspaceUpdated?: () => void;
  onWorkspaceDeleted?: () => void;
}

export function EditWorkspaceModal({ 
  workspace, 
  open, 
  onClose, 
  onWorkspaceUpdated,
  onWorkspaceDeleted 
}: EditWorkspaceModalProps) {
  const [showTokens, setShowTokens] = useState(false);
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'success' | 'error'>('idle');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
    getValues,
  } = useForm<EditWorkspaceFormData>({
    resolver: zodResolver(editWorkspaceSchema),
    defaultValues: {
      team_name: workspace?.team_name || '',
      bot_token: 'xoxb-***-***-***',
      app_token: 'xapp-***-***-***',
      signing_secret: '********************************',
    },
  });

  const testConnection = async () => {
    const values = getValues();
    setIsTestingConnection(true);
    setConnectionStatus('idle');

    try {
      await apiClient.testWorkspaceConnection(workspace!.workspace_id, {
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

  const onSubmit = async (data: EditWorkspaceFormData) => {
    setIsSubmitting(true);
    try {
      await apiClient.updateWorkspace(workspace!.workspace_id, data);
      
      onWorkspaceUpdated?.();
      onClose();
      setConnectionStatus('idle');
    } catch (error) {
      console.error('Failed to update workspace:', error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await apiClient.deleteWorkspace(workspace!.workspace_id);
      
      onWorkspaceDeleted?.();
      onClose();
      setShowDeleteConfirm(false);
    } catch (error) {
      console.error('Failed to delete workspace:', error);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleClose = () => {
    onClose();
    reset();
    setConnectionStatus('idle');
    setShowTokens(false);
    setShowDeleteConfirm(false);
  };

  if (!workspace) return null;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Edit Workspace: {workspace.team_name}</DialogTitle>
        </DialogHeader>
        
        {!showDeleteConfirm ? (
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
              <div className="relative">
                <Input
                  id="bot_token"
                  type={showTokens ? 'text' : 'password'}
                  placeholder="xoxb-..."
                  {...register('bot_token')}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="absolute right-0 top-0 h-full px-3"
                  onClick={() => setShowTokens(!showTokens)}
                >
                  {showTokens ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
              {errors.bot_token && (
                <p className="text-sm text-red-600">{errors.bot_token.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="app_token">App Token</Label>
              <div className="relative">
                <Input
                  id="app_token"
                  type={showTokens ? 'text' : 'password'}
                  placeholder="xapp-..."
                  {...register('app_token')}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="absolute right-0 top-0 h-full px-3"
                  onClick={() => setShowTokens(!showTokens)}
                >
                  {showTokens ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
              {errors.app_token && (
                <p className="text-sm text-red-600">{errors.app_token.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="signing_secret">Signing Secret</Label>
              <div className="relative">
                <Input
                  id="signing_secret"
                  type={showTokens ? 'text' : 'password'}
                  placeholder="Your signing secret"
                  {...register('signing_secret')}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="absolute right-0 top-0 h-full px-3"
                  onClick={() => setShowTokens(!showTokens)}
                >
                  {showTokens ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </Button>
              </div>
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
                      <span className="text-sm text-gray-600">Test connection after changes</span>
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
                onClick={() => setShowDeleteConfirm(true)}
                className="text-red-600 hover:text-red-700"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Delete
              </Button>
              <div className="flex-1" />
              <Button
                type="button"
                variant="outline"
                onClick={handleClose}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={isSubmitting}
              >
                {isSubmitting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Saving...
                  </>
                ) : (
                  'Save Changes'
                )}
              </Button>
            </div>
          </form>
        ) : (
          /* Delete Confirmation */
          <div className="space-y-4">
            <div className="text-center space-y-2">
              <Trash2 className="h-12 w-12 mx-auto text-red-500" />
              <h3 className="text-lg font-semibold">Delete Workspace</h3>
              <p className="text-gray-600">
                Are you sure you want to delete <strong>{workspace.team_name}</strong>?
              </p>
              <p className="text-sm text-red-600">
                This will permanently remove all data and cannot be undone.
              </p>
            </div>
            
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setShowDeleteConfirm(false)}
                className="flex-1"
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleDelete}
                disabled={isDeleting}
                className="flex-1"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  'Delete Workspace'
                )}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}