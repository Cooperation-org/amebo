'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/src/lib/api';
import { toast } from 'sonner';

export function useDocuments(workspaceId?: string) {
  return useQuery({
    queryKey: ['documents', workspaceId],
    queryFn: () => apiClient.getDocuments(workspaceId),
  }) as { data?: { documents: any[] }, isLoading: boolean, error: any };
}

export function useUploadDocuments() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ files, workspaceId }: { files: File[]; workspaceId?: string }) =>
      apiClient.uploadDocuments(files, workspaceId),
    onSuccess: (data) => {
      const { uploaded_count, failed_count } = data;
      
      if (uploaded_count > 0) {
        toast.success(`Successfully uploaded ${uploaded_count} document${uploaded_count !== 1 ? 's' : ''}`);
      }
      
      if (failed_count > 0) {
        toast.error(`Failed to upload ${failed_count} document${failed_count !== 1 ? 's' : ''}`);
      }

      // Invalidate documents queries
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (error: Error) => {
      toast.error(`Upload failed: ${error.message}`);
    },
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId: string) => apiClient.deleteDocument(documentId),
    onSuccess: () => {
      toast.success('Document deleted successfully');
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (error: Error) => {
      toast.error(`Failed to delete document: ${error.message}`);
    },
  });
}

export function useClearAllDocuments() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => apiClient.clearAllDocuments(),
    onSuccess: (data) => {
      const { documents_deleted, collections_deleted } = data;
      toast.success(`Cleared ${documents_deleted} documents and ${collections_deleted?.length || 0} collections`);
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: (error: Error) => {
      toast.error(`Failed to clear documents: ${error.message}`);
    },
  });
}