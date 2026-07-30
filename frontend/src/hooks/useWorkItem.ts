import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type WorkEdit, type WorkItemDetail } from '@/src/lib/api';

export type { WorkItemDetail };

/** The whole record behind a row, plus what people said on it. */
export function useWorkItem(subject: string | null) {
  return useQuery<WorkItemDetail>({
    queryKey: ['work-item', subject],
    queryFn: () => apiClient.getWorkItem(subject as string),
    enabled: !!subject,
    staleTime: 15 * 1000,
    // A refetch while the sheet is open used to overwrite unsaved words. The
    // fields also guard themselves, but not re-fetching under someone's hands
    // is the simpler half of the fix.
    refetchOnWindowFocus: false,
  });
}

/**
 * Applies the change straight away. No draft, no approval step: the gate exists
 * to stop the claw acting alone, and this is the human's own hand.
 */
export function useEditWorkItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: WorkEdit) => apiClient.editWorkItem(body),
    onSuccess: () => {
      // The whole prefix, not one subject: a sheet opened from a claw row is
      // keyed by the row's subject but edits carry the shown task's subject —
      // invalidating only the edited subject left the open sheet stale.
      qc.invalidateQueries({ queryKey: ['work-item'] });
      qc.invalidateQueries({ queryKey: ['work-list'] });
    },
  });
}
