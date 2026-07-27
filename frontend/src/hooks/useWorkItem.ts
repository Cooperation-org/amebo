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
    onSuccess: (_data, body) => {
      qc.invalidateQueries({ queryKey: ['work-item', body.subject] });
      qc.invalidateQueries({ queryKey: ['work-list'] });
    },
  });
}
