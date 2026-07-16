import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type WhiteboardEntry } from '@/src/lib/api';

export type { WhiteboardEntry };

export function useWhiteboard() {
  return useQuery({
    queryKey: ['whiteboard'],
    queryFn: () => apiClient.getWhiteboard(),
    staleTime: 15 * 1000,
    refetchInterval: 30 * 1000,
  });
}

export function useAddWhiteboardEntry() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => apiClient.addWhiteboardEntry(text),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['whiteboard'] }),
  });
}
