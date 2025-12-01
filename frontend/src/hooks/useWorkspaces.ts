import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/src/lib/api';

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

export function useWorkspaces() {
  return useQuery({
    queryKey: ['workspaces'],
    queryFn: async () => {
      const response = await apiClient.getWorkspaces();
      return response as { workspaces: Workspace[]; total: number };
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useWorkspaceChannels(workspaceId?: string) {
  return useQuery({
    queryKey: ['workspace-channels', workspaceId],
    queryFn: async () => {
      if (!workspaceId) return { channels: [] };
      const response = await apiClient.getWorkspaceChannels(workspaceId);
      return response as { channels: Array<{ id: string; name: string }> };
    },
    enabled: !!workspaceId,
    staleTime: 10 * 60 * 1000, // 10 minutes
  });
}

export function useTriggerBackfill() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async ({ workspaceId, days }: { workspaceId: string; days: number }) => {
      return await apiClient.triggerBackfill(workspaceId, days);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}