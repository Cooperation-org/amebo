'use client';

import { useState } from 'react';
import { QuestionInput } from '@/src/components/qa/QuestionInput';
import { AnswerDisplay } from '@/src/components/qa/AnswerDisplay';
import { FilterSidebar } from '@/src/components/qa/FilterSidebar';
import { QueryHistory } from '@/src/components/qa/QueryHistory';
import { Card, CardContent } from '@/components/ui/card';
import { MessageSquare, Sparkles } from 'lucide-react';
import { useAskQuestion } from '@/src/hooks/useQA';
import { toast } from 'sonner';

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

interface FilterOptions {
  workspaceId?: string;
  channelFilter?: string;
  daysBack?: number;
  includeDocuments?: boolean;
  includeSlack?: boolean;
  maxSources?: number;
}

export default function QAPage() {
  const [response, setResponse] = useState<QAResponse | null>(null);
  const [currentQuestion, setCurrentQuestion] = useState('');
  const [filters, setFilters] = useState<FilterOptions>({
    daysBack: 30,
    includeDocuments: true,
    includeSlack: true,
    maxSources: 10,
  });

  const askQuestionMutation = useAskQuestion();

  const handleAskQuestion = async (question: string) => {
    setCurrentQuestion(question);
    try {
      const qaResponse = await askQuestionMutation.mutateAsync({
        question,
        workspace_id: filters.workspaceId,
        channel_filter: filters.channelFilter,
        days_back: filters.daysBack,
        include_documents: filters.includeDocuments,
        include_slack: filters.includeSlack,
        max_sources: filters.maxSources,
      });

      setResponse(qaResponse);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to get answer');
    }
  };

  const handleSelectFromHistory = (question: string) => {
    handleAskQuestion(question);
  };

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-2">
          <MessageSquare className="h-8 w-8 text-blue-600" />
          Q&A Assistant
        </h1>
        <p className="mt-2 text-gray-600">
          Ask questions about your Slack conversations and documents
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Sidebar */}
        <div className="lg:col-span-1 space-y-6">
          <FilterSidebar
            filters={filters}
            onFiltersChange={setFilters}
            isLoading={askQuestionMutation.isPending}
          />
          <QueryHistory onSelectQuery={handleSelectFromHistory} />
        </div>

        {/* Main Content */}
        <div className="lg:col-span-3 space-y-6">
          {/* Question Input */}
          <QuestionInput
            onSubmit={handleAskQuestion}
            isLoading={askQuestionMutation.isPending}
          />

          {/* Answer Display */}
          {response ? (
            <AnswerDisplay response={response} />
          ) : (
            <Card>
              <CardContent className="p-12 text-center">
                <div className="flex flex-col items-center space-y-4">
                  <div className="p-4 bg-blue-100 rounded-full">
                    <Sparkles className="h-8 w-8 text-blue-600" />
                  </div>
                  <div className="space-y-2">
                    <h3 className="text-lg font-medium text-gray-900">
                      Ready to help you find answers
                    </h3>
                    <p className="text-gray-600 max-w-md">
                      Ask any question about your Slack conversations, team discussions, 
                      or uploaded documents. I'll search through your workspace to find 
                      the most relevant information.
                    </p>
                  </div>
                  <div className="text-sm text-gray-500 space-y-1">
                    <p><strong>Try asking:</strong></p>
                    <ul className="text-left space-y-1">
                      <li>• "How do we deploy to production?"</li>
                      <li>• "What's our code review process?"</li>
                      <li>• "Who handles customer support issues?"</li>
                    </ul>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}