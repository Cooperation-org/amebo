import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type Goal } from '@/src/lib/api';

export type { Goal };

/** Goals waiting on a human answer, lowest score first (unscored last). */
export function useNeedsInput() {
  return useQuery({
    queryKey: ['needs-input'],
    queryFn: async () => {
      const goals = await apiClient.getGoals('waiting_user');
      return goals.sort((a, b) => {
        const sa = a.config?.score ?? Number.POSITIVE_INFINITY;
        const sb = b.config?.score ?? Number.POSITIVE_INFINITY;
        return sa === sb ? a.title.localeCompare(b.title) : sa - sb;
      });
    },
    staleTime: 30 * 1000,
    refetchInterval: 60 * 1000,
  });
}

export function useAnswerGoal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) =>
      apiClient.answerGoal(id, answer),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['needs-input'] }),
  });
}
