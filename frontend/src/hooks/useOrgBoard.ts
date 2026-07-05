import { useQuery } from '@tanstack/react-query';
import { apiClient, type OrgBoard } from '@/src/lib/api';

export type { OrgBoard };

export function useOrgBoard() {
  return useQuery({
    queryKey: ['org-board'],
    queryFn: async () => {
      return (await apiClient.getOrgBoard()) as OrgBoard;
    },
    staleTime: 60 * 1000, // matches the backend's freshness window
  });
}
