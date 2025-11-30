'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ArrowLeft, Settings, Users, MessageSquare, Calendar } from 'lucide-react';
import { useWorkspaces } from '@/src/hooks/useWorkspaces';
import { BackfillScheduler } from '@/src/components/workspaces/BackfillScheduler';
import { BackfillHistory } from '@/src/components/workspaces/BackfillHistory';

export default function WorkspaceDetailPage() {
  const params = useParams();
  const router = useRouter();
  const workspaceId = params.id as string;
  
  const { data: workspacesData, isLoading } = useWorkspaces();
  const workspace = workspacesData?.workspaces?.find(w => w.workspace_id === workspaceId);

  // Mock data for backfill jobs
  const mockJobs = [
    {
      job_run_id: 1,
      job_type: 'manual' as const,
      status: 'success' as const,
      messages_collected: 1250,
      channels_processed: 8,
      started_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
      completed_at: new Date(Date.now() - 2 * 60 * 60 * 1000 + 5 * 60 * 1000).toISOString(),
    },
    {
      job_run_id: 2,
      job_type: 'scheduled' as const,
      status: 'success' as const,
      messages_collected: 45,
      channels_processed: 3,
      started_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      completed_at: new Date(Date.now() - 24 * 60 * 60 * 1000 + 2 * 60 * 1000).toISOString(),
    },
    {
      job_run_id: 3,
      job_type: 'scheduled' as const,
      status: 'failed' as const,
      messages_collected: 0,
      channels_processed: 0,
      started_at: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
      completed_at: new Date(Date.now() - 48 * 60 * 60 * 1000 + 30 * 1000).toISOString(),
      error_message: 'Invalid bot token - authentication failed',
    },
  ];

  const getStatusBadge = (status?: string) => {
    switch (status) {
      case 'active':
        return <Badge className="bg-green-100 text-green-800">✅ Active</Badge>;
      case 'syncing':
        return <Badge className="bg-blue-100 text-blue-800">🔄 Syncing</Badge>;
      case 'error':
        return <Badge className="bg-red-100 text-red-800">❌ Error</Badge>;
      default:
        return <Badge variant="secondary">Unknown</Badge>;
    }
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'Never';
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <div className="h-8 w-8 bg-gray-200 rounded animate-pulse"></div>
          <div className="h-8 w-48 bg-gray-200 rounded animate-pulse"></div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[1, 2, 3, 4].map(i => (
            <Card key={i} className="animate-pulse">
              <CardHeader>
                <div className="h-6 bg-gray-200 rounded w-1/2"></div>
              </CardHeader>
              <CardContent>
                <div className="h-20 bg-gray-200 rounded"></div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  if (!workspace) {
    return (
      <div className="text-center py-12">
        <h2 className="text-2xl font-bold mb-4">Workspace not found</h2>
        <Button onClick={() => router.push('/dashboard/workspaces')}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Workspaces
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button
            variant="outline"
            size="sm"
            onClick={() => router.push('/dashboard/workspaces')}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-3xl font-bold">{workspace.team_name}</h1>
            <div className="flex items-center gap-2 mt-1">
              {getStatusBadge(workspace.status)}
              <span className="text-gray-500">•</span>
              <span className="text-gray-500">{workspace.workspace_id}</span>
            </div>
          </div>
        </div>
        <Button variant="outline">
          <Settings className="h-4 w-4 mr-2" />
          Edit Workspace
        </Button>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <MessageSquare className="h-8 w-8 text-blue-600" />
              <div>
                <p className="text-2xl font-bold">{workspace.message_count?.toLocaleString() || '0'}</p>
                <p className="text-sm text-gray-600">Messages</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <Users className="h-8 w-8 text-green-600" />
              <div>
                <p className="text-2xl font-bold">{workspace.channel_count || '0'}</p>
                <p className="text-sm text-gray-600">Channels</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <Calendar className="h-8 w-8 text-purple-600" />
              <div>
                <p className="text-sm font-medium">Installed</p>
                <p className="text-sm text-gray-600">{formatDate(workspace.installed_at)}</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center gap-3">
              <Calendar className="h-8 w-8 text-orange-600" />
              <div>
                <p className="text-sm font-medium">Last Sync</p>
                <p className="text-sm text-gray-600">{formatDate(workspace.last_sync_at)}</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Backfill Configuration */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <BackfillScheduler
          workspaceId={workspaceId}
          currentSchedule={{
            cron_expression: '0 2 * * *',
            days_to_backfill: 7,
            is_active: true,
          }}
          onScheduleUpdate={(schedule) => {
            console.log('Schedule updated:', schedule);
          }}
          onManualSync={() => {
            console.log('Manual sync triggered');
          }}
        />

        <BackfillHistory
          workspaceId={workspaceId}
          jobs={mockJobs}
          onRefresh={() => {
            console.log('Refreshing history');
          }}
        />
      </div>
    </div>
  );
}