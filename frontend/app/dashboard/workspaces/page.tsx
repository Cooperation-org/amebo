'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Plus, Search, Grid, List } from 'lucide-react';
import { useWorkspaces } from '@/src/hooks/useWorkspaces';
import { useWorkspaceSync } from '@/src/hooks/useWorkspaceSync';
import { WorkspaceCard } from '@/src/components/workspaces/WorkspaceCard';
import { AddWorkspaceModal } from '@/src/components/workspaces/AddWorkspaceModal';
import { EditWorkspaceModal } from '@/src/components/workspaces/EditWorkspaceModal';

export default function WorkspacesPage() {
  const { data: workspacesData, isLoading } = useWorkspaces();
  const syncWorkspace = useWorkspaceSync();
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [editingWorkspace, setEditingWorkspace] = useState<any>(null);

  const workspaces = workspacesData?.workspaces || [];

  const filteredWorkspaces = workspaces.filter(workspace => {
    const matchesSearch = workspace.team_name.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'all' || workspace.status === statusFilter;
    return matchesSearch && matchesStatus;
  });



  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold">Workspaces</h1>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2, 3].map(i => (
            <Card key={i} className="animate-pulse">
              <CardHeader>
                <div className="h-4 bg-gray-200 rounded w-3/4"></div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="h-3 bg-gray-200 rounded w-1/2"></div>
                  <div className="h-3 bg-gray-200 rounded w-2/3"></div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold">Workspaces</h1>
        <AddWorkspaceModal onWorkspaceAdded={() => window.location.reload()} />
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center justify-between">
        <div className="flex gap-4 flex-1">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-4 w-4" />
            <Input
              placeholder="Search workspaces..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder="Filter by status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="syncing">Syncing</SelectItem>
              <SelectItem value="error">Error</SelectItem>
            </SelectContent>
          </Select>
        </div>
        
        <div className="flex gap-2">
          <Button
            variant={viewMode === 'grid' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setViewMode('grid')}
          >
            <Grid className="h-4 w-4" />
          </Button>
          <Button
            variant={viewMode === 'list' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setViewMode('list')}
          >
            <List className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Workspace Grid/List */}
      {filteredWorkspaces.length === 0 ? (
        <Card className="p-12 text-center">
          <div className="text-gray-500">
            {searchQuery || statusFilter !== 'all' ? (
              <>
                <Search className="h-12 w-12 mx-auto mb-4 text-gray-300" />
                <h3 className="text-lg font-medium mb-2">No workspaces found</h3>
                <p>Try adjusting your search or filter criteria.</p>
              </>
            ) : (
              <>
                <Plus className="h-12 w-12 mx-auto mb-4 text-gray-300" />
                <h3 className="text-lg font-medium mb-2">No workspaces yet</h3>
                <p className="mb-4">Connect your first Slack workspace to get started.</p>
                <AddWorkspaceModal onWorkspaceAdded={() => window.location.reload()} />
              </>
            )}
          </div>
        </Card>
      ) : (
        <div className={viewMode === 'grid' 
          ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
          : "space-y-4"
        }>
          {filteredWorkspaces.map((workspace) => (
            <WorkspaceCard
              key={workspace.workspace_id}
              workspace={workspace}
              onEdit={(ws) => setEditingWorkspace(ws)}
              onDelete={(ws) => setEditingWorkspace(ws)}
              onSync={(ws) => syncWorkspace.mutate(ws.workspace_id)}
            />
          ))}
        </div>
      )}
      
      <EditWorkspaceModal
        workspace={editingWorkspace}
        open={!!editingWorkspace}
        onClose={() => setEditingWorkspace(null)}
        onWorkspaceUpdated={() => {
          setEditingWorkspace(null);
          window.location.reload();
        }}
        onWorkspaceDeleted={() => {
          setEditingWorkspace(null);
          window.location.reload();
        }}
      />
    </div>
  );
}