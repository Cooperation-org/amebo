import { useQuery } from '@tanstack/react-query';
import { apiClient, type WorkItem, type WorkList } from '@/src/lib/api';

export type { WorkItem, WorkList };

/**
 * The one ranked list. The server has already ordered `live` by rank and split
 * out what went past its date, so the client renders the order it is given
 * rather than inventing a second opinion. Every item still carries `rank` and
 * `reason.kind`, so a re-rank or filter control can be added here later without
 * a backend change.
 */
export function useWorkList() {
  return useQuery<WorkList>({
    queryKey: ['work-list'],
    queryFn: () => apiClient.getWorkList(),
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}
