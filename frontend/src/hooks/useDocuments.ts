'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/src/lib/api';

interface Document {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  status: 'processing' | 'indexed' | 'failed';
  upload_date: string;
  error_message?: string;
}

interface DocumentsResponse {
  documents: Document[];
  total: number;
}

// Get all documents
export function useDocuments() {
  return useQuery<Document[]>({
    queryKey: ['documents'],
    queryFn: async () => {
      const response = await apiClient.get('/api/documents');
      return response.data.documents || [];
    },
    staleTime: 30000, // 30 seconds
  });
}

// Upload document
export function useUploadDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);

      const response = await apiClient.post('/api/documents/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      return response.data;
    },
    onSuccess: () => {
      // Invalidate and refetch documents
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}

// Delete document
export function useDeleteDocument() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (documentId: string) => {
      const response = await apiClient.delete(`/api/documents/${documentId}`);
      return response.data;
    },
    onSuccess: () => {
      // Invalidate and refetch documents
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}

// Get document content (for preview)
export function useDocumentContent(documentId: string) {
  return useQuery({
    queryKey: ['document-content', documentId],
    queryFn: async () => {
      const response = await apiClient.get(`/api/documents/${documentId}/content`);
      return response.data;
    },
    enabled: !!documentId,
  });
}

// Bulk delete documents
export function useBulkDeleteDocuments() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (documentIds: string[]) => {
      const response = await apiClient.post('/api/documents/bulk-delete', {
        document_ids: documentIds,
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}