'use client';

import { useState, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Filter, RotateCcw, Search } from 'lucide-react';
import { useWorkspaces, useWorkspaceChannels } from '@/src/hooks/useWorkspaces';

interface FilterOptions {
  workspaceId?: string;
  channelFilter?: string[];
  daysBack?: number;
  includeDocuments?: boolean;
  includeSlack?: boolean;
  maxSources?: number;
}

interface FilterSidebarProps {
  filters: FilterOptions;
  onFiltersChange: (filters: FilterOptions) => void;
  isLoading?: boolean;
}

export function FilterSidebar({ 
  filters, 
  onFiltersChange,
  isLoading = false 
}: FilterSidebarProps) {
  const { data: workspacesData } = useWorkspaces();
  const { data: channelsData } = useWorkspaceChannels(filters.workspaceId);
  
  const workspaces = workspacesData?.workspaces || [];
  const channels = channelsData?.channels || [];
  const [localFilters, setLocalFilters] = useState<FilterOptions>(filters);
  const [channelSearch, setChannelSearch] = useState('');
  
  // Debounced channel search
  const filteredChannels = useMemo(() => {
    if (!channelSearch.trim()) return channels;
    return channels.filter(channel => 
      channel.name.toLowerCase().includes(channelSearch.toLowerCase())
    );
  }, [channels, channelSearch]);

  const handleFilterChange = (key: keyof FilterOptions, value: any) => {
    const newFilters = { ...localFilters, [key]: value };
    setLocalFilters(newFilters);
    onFiltersChange(newFilters);
  };

  const handleReset = () => {
    const defaultFilters: FilterOptions = {
      workspaceId: undefined,
      channelFilter: undefined,
      daysBack: undefined,
      includeDocuments: true,
      includeSlack: true,
      maxSources: 10,
    };
    setLocalFilters(defaultFilters);
    onFiltersChange(defaultFilters);
    setChannelSearch('');
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Filters
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleReset}
            className="h-8 px-2"
          >
            <RotateCcw className="h-3 w-3" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Workspace Selection */}
        <div className="space-y-2">
          <Label htmlFor="workspace">Workspace</Label>
          <Select
            value={localFilters.workspaceId || 'all'}
            onValueChange={(value) => handleFilterChange('workspaceId', value === 'all' ? undefined : value)}
            disabled={isLoading}
          >
            <SelectTrigger>
              <SelectValue placeholder="All workspaces" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All workspaces</SelectItem>
              {workspaces.map((workspace) => (
                <SelectItem key={workspace.workspace_id} value={workspace.workspace_id}>
                  {workspace.team_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Channel Filter (Multi-select) */}
        <div className="space-y-2">
          <Label>Channels {localFilters.channelFilter?.length ? `(${localFilters.channelFilter.length})` : '(All)'}</Label>
          {channels.length > 5 && (
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
              <Input
                placeholder="Search channels..."
                value={channelSearch}
                onChange={(e) => setChannelSearch(e.target.value)}
                className="pl-10"
                disabled={isLoading || !localFilters.workspaceId}
              />
            </div>
          )}
          <div className="max-h-48 overflow-y-auto border rounded-md p-2 space-y-1">
            {!localFilters.workspaceId ? (
              <p className="text-xs text-gray-400 py-1">Select a workspace first</p>
            ) : filteredChannels.length === 0 ? (
              <p className="text-xs text-gray-400 py-1">No channels found</p>
            ) : (
              filteredChannels.map((channel) => {
                const isSelected = localFilters.channelFilter?.includes(channel.name) ?? false;
                return (
                  <div key={channel.id} className="flex items-center space-x-2">
                    <Checkbox
                      id={`channel-${channel.id}`}
                      checked={isSelected}
                      disabled={isLoading}
                      onCheckedChange={(checked) => {
                        const current = localFilters.channelFilter || [];
                        const updated = checked
                          ? [...current, channel.name]
                          : current.filter(c => c !== channel.name);
                        handleFilterChange('channelFilter', updated.length > 0 ? updated : undefined);
                      }}
                    />
                    <Label htmlFor={`channel-${channel.id}`} className="text-sm cursor-pointer">
                      #{channel.name}
                    </Label>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Time Range */}
        <div className="space-y-2">
          <Label htmlFor="timeRange">Time Range</Label>
          <Select
            value={localFilters.daysBack?.toString() || '30'}
            onValueChange={(value) => handleFilterChange('daysBack', parseInt(value))}
            disabled={isLoading}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 3 months</SelectItem>
              <SelectItem value="365">Last year</SelectItem>
              <SelectItem value="0">All time</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Source Types */}
        <div className="space-y-3">
          <Label>Source Types</Label>
          <div className="space-y-2">
            <div className="flex items-center space-x-2">
              <Checkbox
                id="includeSlack"
                checked={localFilters.includeSlack ?? true}
                onCheckedChange={(checked) => handleFilterChange('includeSlack', checked)}
                disabled={isLoading}
              />
              <Label htmlFor="includeSlack" className="text-sm">
                Slack Messages
              </Label>
            </div>
            <div className="flex items-center space-x-2">
              <Checkbox
                id="includeDocuments"
                checked={localFilters.includeDocuments ?? true}
                onCheckedChange={(checked) => handleFilterChange('includeDocuments', checked)}
                disabled={isLoading}
              />
              <Label htmlFor="includeDocuments" className="text-sm">
                Documents
              </Label>
            </div>
          </div>
        </div>

        {/* Max Sources */}
        <div className="space-y-2">
          <Label htmlFor="maxSources">Max Sources</Label>
          <Select
            value={localFilters.maxSources?.toString() || '10'}
            onValueChange={(value) => handleFilterChange('maxSources', parseInt(value))}
            disabled={isLoading}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="5">5 sources</SelectItem>
              <SelectItem value="10">10 sources</SelectItem>
              <SelectItem value="20">20 sources</SelectItem>
              <SelectItem value="50">50 sources</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}