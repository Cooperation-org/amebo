import { useQuery } from '@tanstack/react-query';
import { apiClient, type ChatThreadSummary } from '@/src/lib/api';

export type { ChatThreadSummary };

export function useChatThreads() {
  return useQuery({
    queryKey: ['chat-threads'],
    queryFn: async () => {
      return (await apiClient.getChatThreads()) as ChatThreadSummary[];
    },
    staleTime: 60 * 1000,
  });
}
