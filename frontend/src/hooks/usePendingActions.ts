import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type PendingAction } from '@/src/lib/api';

export type { PendingAction };

export function usePendingActions() {
  return useQuery({
    queryKey: ['pending-actions'],
    queryFn: () => apiClient.getPendingActions(),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}

function useDecide(fn: (id: string) => Promise<PendingAction>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['pending-actions'] }),
  });
}

export function useApproveAction() {
  return useDecide((id) => apiClient.approvePendingAction(id));
}

export function useRejectAction() {
  return useDecide((id) => apiClient.rejectPendingAction(id));
}
