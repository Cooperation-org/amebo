'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { toast } from 'sonner';
import { workspaceSchema, type WorkspaceFormData } from '@/src/lib/validations';
import { apiClient } from '@/src/lib/api';
import { CheckCircle, AlertCircle, Loader2 } from 'lucide-react';

interface SlackWorkspaceFormProps {
  onSuccess: () => void;
  onSkip: () => void;
}

export function SlackWorkspaceForm({ onSuccess, onSkip }: SlackWorkspaceFormProps) {
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'idle' | 'success' | 'error'>('idle');

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    getValues,
  } = useForm<WorkspaceFormData>({
    resolver: zodResolver(workspaceSchema),
  });

  const testConnection = async () => {
    const values = getValues();
    
    // Basic validation before testing
    if (!values.botToken || !values.appToken || !values.signingSecret) {
      toast.error('Please fill in all fields before testing connection');
      return;
    }

    setIsTestingConnection(true);
    setConnectionStatus('idle');

    try {
      // Test connection without saving
      await apiClient.testWorkspaceConnection('test', {
        bot_token: values.botToken,
        app_token: values.appToken,
        signing_secret: values.signingSecret,
      });
      
      setConnectionStatus('success');
      toast.success('✅ Connection verified! Your Slack workspace is ready.');
    } catch (error) {
      setConnectionStatus('error');
      const errorMessage = error instanceof Error ? error.message : 'Connection failed';
      toast.error(`❌ Connection failed: ${errorMessage}`);
    } finally {
      setIsTestingConnection(false);
    }
  };

  const onSubmit = async (data: WorkspaceFormData) => {
    try {
      await apiClient.addWorkspace({
        workspace_name: data.workspaceName,
        bot_token: data.botToken,
        app_token: data.appToken,
        signing_secret: data.signingSecret,
      });
      
      toast.success('🎉 Workspace added successfully! Welcome to Amebo Bot.');
      onSuccess();
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Failed to add workspace';
      toast.error(`Failed to add workspace: ${errorMessage}`);
    }
  };

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle>Connect Your Slack Workspace</CardTitle>
        <CardDescription>
          Add your Slack workspace credentials to start using the AI-powered Q&A bot.
          You can find these tokens in your Slack app settings.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="workspaceName">Workspace Name</Label>
            <Input
              id="workspaceName"
              placeholder="e.g., My Company Workspace"
              {...register('workspaceName')}
            />
            {errors.workspaceName && (
              <p className="text-sm text-red-600">{errors.workspaceName.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="botToken">Bot Token</Label>
            <Input
              id="botToken"
              type="password"
              placeholder="xoxb-..."
              {...register('botToken')}
            />
            {errors.botToken && (
              <p className="text-sm text-red-600">{errors.botToken.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="appToken">App Token</Label>
            <Input
              id="appToken"
              type="password"
              placeholder="xapp-..."
              {...register('appToken')}
            />
            {errors.appToken && (
              <p className="text-sm text-red-600">{errors.appToken.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="signingSecret">Signing Secret</Label>
            <Input
              id="signingSecret"
              type="password"
              placeholder="Your signing secret"
              {...register('signingSecret')}
            />
            {errors.signingSecret && (
              <p className="text-sm text-red-600">{errors.signingSecret.message}</p>
            )}
          </div>

          <div className="flex items-center gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={testConnection}
              disabled={isTestingConnection}
              className="flex items-center gap-2"
            >
              {isTestingConnection ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : connectionStatus === 'success' ? (
                <CheckCircle className="h-4 w-4 text-green-600" />
              ) : connectionStatus === 'error' ? (
                <AlertCircle className="h-4 w-4 text-red-600" />
              ) : null}
              {isTestingConnection ? 'Testing...' : 'Test Connection'}
            </Button>
            
            {connectionStatus === 'success' && (
              <span className="text-sm text-green-600 flex items-center gap-1">
                <CheckCircle className="h-4 w-4" />
                Connection verified!
              </span>
            )}
            {connectionStatus === 'error' && (
              <span className="text-sm text-red-600 flex items-center gap-1">
                <AlertCircle className="h-4 w-4" />
                Please check your credentials
              </span>
            )}
          </div>

          <div className="flex gap-3 pt-4">
            <Button
              type="submit"
              disabled={isSubmitting || connectionStatus !== 'success'}
              className="flex-1"
            >
              {isSubmitting ? 'Adding Workspace...' : 'Add Workspace'}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={onSkip}
              disabled={isSubmitting}
            >
              Skip for now
            </Button>
          </div>
        </form>

        <div className="mt-6 p-4 bg-blue-50 rounded-lg">
          <h4 className="font-medium text-blue-900 mb-2">Need help finding your tokens?</h4>
          <ul className="text-sm text-blue-800 space-y-1">
            <li>• Go to your Slack app settings at api.slack.com</li>
            <li>• Bot Token: OAuth & Permissions → Bot User OAuth Token</li>
            <li>• App Token: Basic Information → App-Level Tokens</li>
            <li>• Signing Secret: Basic Information → Signing Secret</li>
          </ul>
        </div>
      </CardContent>
    </Card>
  );
}