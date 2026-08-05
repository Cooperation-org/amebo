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
  // Amebo's own changes arrive over the stream (useWorkListLive), so this is
  // no longer how the list stays current — it is the fallback for the one case
  // the stream cannot cover: a story edited directly in Marten, or a follow-up
  // rescheduled in the CRM. Those are rare, so the check is slow.
  return useQuery<WorkList>({
    queryKey: ['work-list'],
    queryFn: () => apiClient.getWorkList(),
    staleTime: 30 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });
}
