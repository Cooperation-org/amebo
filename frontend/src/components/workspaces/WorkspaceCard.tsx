'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Settings, Trash2, RefreshCw } from 'lucide-react';

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

interface WorkspaceCardProps {
  workspace: Workspace;
  onEdit?: (workspace: Workspace) => void;
  onDelete?: (workspace: Workspace) => void;
  onSync?: (workspace: Workspace) => void;
}

export function WorkspaceCard({ workspace, onEdit, onDelete, onSync }: WorkspaceCardProps) {
  const getStatusBadge = (status: string) => {
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

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex justify-between items-start">
          <CardTitle className="text-lg">{workspace.team_name}</CardTitle>
          {getStatusBadge(workspace.status || 'active')}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div>
            <p className="text-gray-500">Messages</p>
            <p className="font-medium">{workspace.message_count?.toLocaleString() || '0'}</p>
          </div>
          <div>
            <p className="text-gray-500">Channels</p>
            <p className="font-medium">{workspace.channel_count || '0'}</p>
          </div>
        </div>
        
        <div className="text-sm">
          <p className="text-gray-500">Last sync</p>
          <p className="font-medium">
            {workspace.last_sync_at 
              ? formatDate(workspace.last_sync_at)
              : 'Never'
            }
          </p>
        </div>

        <div className="flex gap-2 pt-2">
          <Button 
            variant="outline" 
            size="sm" 
            className="flex-1"
            onClick={() => onEdit?.(workspace)}
          >
            <Settings className="h-3 w-3 mr-1" />
            Edit
          </Button>
          <Button 
            variant="outline" 
            size="sm"
            onClick={() => onSync?.(workspace)}
            disabled={workspace.status === 'syncing'}
          >
            <RefreshCw className={`h-3 w-3 ${workspace.status === 'syncing' ? 'animate-spin' : ''}`} />
          </Button>
          <Button 
            variant="outline" 
            size="sm" 
            className="text-red-600 hover:text-red-700"
            onClick={() => onDelete?.(workspace)}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}