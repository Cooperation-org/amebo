import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient, type OrgLink } from '@/src/lib/api';

export type { OrgLink };

export function useOrgLinks() {
  return useQuery({
    queryKey: ['org-links'],
    queryFn: async () => {
      const response = await apiClient.getOrgLinks();
      return response.links;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useSetOrgLinks() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (links: OrgLink[]) => {
      const response = await apiClient.setOrgLinks(links);
      return response.links;
    },
    onSuccess: (links) => {
      queryClient.setQueryData(['org-links'], links);
    },
  });
}
