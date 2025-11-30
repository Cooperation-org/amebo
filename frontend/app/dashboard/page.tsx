'use client';

import { useAuthStore } from '@/src/store/useAuthStore';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { MessageSquare, Building2, Users, Settings, FileText, TrendingUp, Clock, Plus } from 'lucide-react';
import Link from 'next/link';
import { useWorkspaces } from '@/src/hooks/useWorkspaces';
import { useDocuments } from '@/src/hooks/useDocuments';
import { useQueryHistory } from '@/src/hooks/useQA';

export default function DashboardPage() {
  const { user } = useAuthStore();
  const { data: workspacesData } = useWorkspaces();
  const { data: documents = [] } = useDocuments();
  const { data: queryHistory = [] } = useQueryHistory();

  const workspaces = workspacesData?.workspaces || [];
  const hasWorkspaces = workspaces.length > 0;
  const totalMessages = workspaces.reduce((sum, ws) => sum + (ws.message_count || 0), 0);
  const activeWorkspaces = workspaces.filter(ws => ws.status === 'active').length;
  const indexedDocuments = documents.filter(doc => doc.status === 'indexed').length;
  const thisMonthQueries = queryHistory.filter((q: any) => {
    const queryDate = new Date(q.timestamp);
    const now = new Date();
    return queryDate.getMonth() === now.getMonth() && queryDate.getFullYear() === now.getFullYear();
  }).length;

  const recentActivity = [
    ...queryHistory.slice(0, 3).map((q: any) => ({
      type: 'query',
      title: q.question,
      time: q.timestamp,
      confidence: q.confidence,
    })),
    ...workspaces.slice(0, 2).map(ws => ({
      type: 'workspace',
      title: `Synced ${ws.team_name}`,
      time: ws.last_sync_at || ws.created_at,
    })),
  ].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()).slice(0, 5);

  const formatTimeAgo = (timestamp: string) => {
    if (!timestamp) return 'Unknown';
    
    const now = new Date();
    const time = new Date(timestamp);
    
    // Check if date is valid
    if (isNaN(time.getTime())) return 'Unknown';
    
    const diffMs = now.getTime() - time.getTime();
    const diffMins = Math.floor(diffMs / (1000 * 60));
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">
          Welcome back, {user?.full_name || user?.email}!
        </h1>
        <p className="mt-2 text-gray-600">
          Here's what's happening with your AI assistant
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Active Workspaces</p>
                <p className="text-2xl font-bold text-gray-900">{activeWorkspaces}</p>
              </div>
              <Building2 className="h-8 w-8 text-green-600" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Messages Indexed</p>
                <p className="text-2xl font-bold text-gray-900">{totalMessages.toLocaleString()}</p>
              </div>
              <MessageSquare className="h-8 w-8 text-blue-600" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Queries This Month</p>
                <p className="text-2xl font-bold text-gray-900">{thisMonthQueries}</p>
              </div>
              <TrendingUp className="h-8 w-8 text-purple-600" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Documents</p>
                <p className="text-2xl font-bold text-gray-900">{indexedDocuments}</p>
              </div>
              <FileText className="h-8 w-8 text-orange-600" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Quick Actions */}
        <div className="lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle>Quick Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button 
                asChild={hasWorkspaces} 
                className="w-full justify-start" 
                disabled={!hasWorkspaces}
              >
                {hasWorkspaces ? (
                  <Link href="/dashboard/qa">
                    <MessageSquare className="h-4 w-4 mr-2" />
                    Ask a Question
                  </Link>
                ) : (
                  <>
                    <MessageSquare className="h-4 w-4 mr-2" />
                    Ask a Question (Add workspace first)
                  </>
                )}
              </Button>
              <Button asChild variant="outline" className="w-full justify-start">
                <Link href="/dashboard/workspaces">
                  <Plus className="h-4 w-4 mr-2" />
                  Add Workspace
                </Link>
              </Button>
              <Button asChild variant="outline" className="w-full justify-start">
                <Link href="/dashboard/documents">
                  <FileText className="h-4 w-4 mr-2" />
                  Upload Document
                </Link>
              </Button>
              <Button asChild variant="outline" className="w-full justify-start">
                <Link href="/dashboard/team">
                  <Users className="h-4 w-4 mr-2" />
                  Invite Team Member
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>

        {/* Recent Activity */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="h-5 w-5" />
                Recent Activity
              </CardTitle>
            </CardHeader>
            <CardContent>
              {recentActivity.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <Clock className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p className="text-sm">No recent activity</p>
                  <p className="text-xs text-gray-400 mt-1">
                    Start by asking a question or adding a workspace
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {recentActivity.map((activity, index) => (
                    <div key={index} className="flex items-start space-x-3 p-3 rounded-lg hover:bg-gray-50">
                      <div className="flex-shrink-0">
                        {activity.type === 'query' ? (
                          <MessageSquare className="h-5 w-5 text-blue-600 mt-0.5" />
                        ) : (
                          <Building2 className="h-5 w-5 text-green-600 mt-0.5" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">
                          {activity.title}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <span className="text-xs text-gray-500">
                            {formatTimeAgo(activity.time)}
                          </span>
                          {activity.type === 'query' && activity.confidence && (
                            <Badge variant="secondary" className="text-xs">
                              {Math.round(activity.confidence)}% confidence
                            </Badge>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}