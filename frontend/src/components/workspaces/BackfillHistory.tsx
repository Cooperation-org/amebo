'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { History, RefreshCw, CheckCircle, XCircle, Clock } from 'lucide-react';

interface BackfillJob {
  job_run_id: number;
  job_type: 'scheduled' | 'manual';
  status: 'running' | 'success' | 'failed';
  messages_collected: number;
  channels_processed: number;
  started_at: string;
  completed_at?: string;
  error_message?: string;
}

interface BackfillHistoryProps {
  workspaceId: string;
  jobs?: BackfillJob[];
  isLoading?: boolean;
  onRefresh?: () => void;
}

export function BackfillHistory({ 
  workspaceId, 
  jobs = [], 
  isLoading = false,
  onRefresh 
}: BackfillHistoryProps) {
  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircle className="h-4 w-4 text-green-600" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-600" />;
      case 'running':
        return <RefreshCw className="h-4 w-4 text-blue-600 animate-spin" />;
      default:
        return <Clock className="h-4 w-4 text-gray-400" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'success':
        return <Badge className="bg-green-100 text-green-800">Success</Badge>;
      case 'failed':
        return <Badge className="bg-red-100 text-red-800">Failed</Badge>;
      case 'running':
        return <Badge className="bg-blue-100 text-blue-800">Running</Badge>;
      default:
        return <Badge variant="secondary">Unknown</Badge>;
    }
  };

  const formatDuration = (startedAt: string, completedAt?: string) => {
    const start = new Date(startedAt);
    const end = completedAt ? new Date(completedAt) : new Date();
    const duration = Math.round((end.getTime() - start.getTime()) / 1000);
    
    if (duration < 60) return `${duration}s`;
    if (duration < 3600) return `${Math.round(duration / 60)}m`;
    return `${Math.round(duration / 3600)}h`;
  };

  const formatDateTime = (dateString: string) => {
    return new Date(dateString).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5" />
            Backfill History
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="animate-pulse">
                <div className="h-16 bg-gray-200 rounded"></div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5" />
            Backfill History
          </CardTitle>
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {jobs.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <History className="h-12 w-12 mx-auto mb-4 text-gray-300" />
            <p>No backfill jobs yet</p>
            <p className="text-sm">Trigger a manual sync to see history</p>
          </div>
        ) : (
          <div className="space-y-3">
            {jobs.map((job) => (
              <div
                key={job.job_run_id}
                className="border rounded-lg p-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    {getStatusIcon(job.status)}
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium capitalize">{job.job_type}</span>
                        {getStatusBadge(job.status)}
                      </div>
                      <p className="text-sm text-gray-600">
                        Started {formatDateTime(job.started_at)}
                      </p>
                    </div>
                  </div>
                  
                  <div className="text-right text-sm">
                    <p className="font-medium">
                      {job.messages_collected.toLocaleString()} messages
                    </p>
                    <p className="text-gray-500">
                      {job.channels_processed} channels
                    </p>
                  </div>
                </div>

                <div className="mt-3 flex items-center justify-between text-sm text-gray-500">
                  <span>
                    Duration: {formatDuration(job.started_at, job.completed_at)}
                  </span>
                  {job.completed_at && (
                    <span>
                      Completed {formatDateTime(job.completed_at)}
                    </span>
                  )}
                </div>

                {job.error_message && (
                  <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
                    <strong>Error:</strong> {job.error_message}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}