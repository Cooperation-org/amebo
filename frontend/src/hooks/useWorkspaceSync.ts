import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/src/lib/api';

export function useWorkspaceSync() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (workspaceId: string) => {
      return apiClient.syncWorkspace(workspaceId);
    },
    onSuccess: () => {
      // Invalidate workspaces query to refresh the list
      queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });
}