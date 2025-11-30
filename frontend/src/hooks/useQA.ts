import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/src/lib/api';

interface QARequest {
  question: string;
  workspace_id?: string;
  channel_filter?: string;
  days_back?: number;
  include_documents?: boolean;
  include_slack?: boolean;
  max_sources?: number;
}

interface QAResponse {
  answer: string;
  confidence: number;
  confidence_explanation?: string;
  project_links?: Array<{
    url: string;
    title: string;
    type: string;
  }>;
  sources: Array<{
    source_type: string;
    text: string;
    metadata: any;
    relevance_score?: number;
  }>;
  question: string;
  processing_time_ms?: number;
}

interface QueryHistoryItem {
  id: string;
  question: string;
  answer: string;
  confidence: number;
  timestamp: string;
  workspace_id?: string;
}

export function useAskQuestion() {
  const queryClient = useQueryClient();
  
  return useMutation({
    mutationFn: async (params: QARequest): Promise<QAResponse> => {
      const response = await apiClient.askQuestion(params);
      return response as QAResponse;
    },
    onSuccess: (data, variables) => {
      // Add to query history
      const historyItem: QueryHistoryItem = {
        id: Date.now().toString(),
        question: variables.question,
        answer: data.answer,
        confidence: data.confidence,
        timestamp: new Date().toISOString(),
        workspace_id: variables.workspace_id,
      };
      
      queryClient.setQueryData(['query-history'], (old: QueryHistoryItem[] = []) => {
        return [historyItem, ...old.slice(0, 49)]; // Keep last 50 queries
      });
    },
  });
}

export function useQueryHistory() {
  return useQuery({
    queryKey: ['query-history'],
    queryFn: () => {
      // Get from localStorage for persistence
      if (typeof window !== 'undefined') {
        const stored = localStorage.getItem('qa-history');
        return stored ? JSON.parse(stored) : [];
      }
      return [];
    },
    staleTime: Infinity, // Never stale
  });
}

export function useSaveQueryHistory() {
  const queryClient = useQueryClient();
  
  return (history: QueryHistoryItem[]) => {
    // Save to localStorage
    if (typeof window !== 'undefined') {
      localStorage.setItem('qa-history', JSON.stringify(history));
    }
    queryClient.setQueryData(['query-history'], history);
  };
}