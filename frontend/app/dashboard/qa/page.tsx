'use client';

import { useState, useEffect } from 'react';
import { QuestionInput } from '@/src/components/qa/QuestionInput';
import { AnswerDisplay } from '@/src/components/qa/AnswerDisplay';
import { FilterSidebar } from '@/src/components/qa/FilterSidebar';
import { QueryHistory } from '@/src/components/qa/QueryHistory';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { MessageSquare, Sparkles, Building2, Plus } from 'lucide-react';
import { useAskQuestion } from '@/src/hooks/useQA';
import { useWorkspaces } from '@/src/hooks/useWorkspaces';
import { toast } from 'sonner';
import Link from 'next/link';

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
  const { data: workspacesData } = useWorkspaces();
  const workspaces = workspacesData?.workspaces || [];
  const hasWorkspaces = workspaces.length > 0;

  const handleAskQuestion = async (question: string) => {
    if (!hasWorkspaces) {
      toast.error('Please connect a workspace first to ask questions');
      return;
    }

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
      console.error('Q&A Error:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to get answer');
    }
  };

  const handleSelectFromHistory = (question: string) => {
    handleAskQuestion(question);
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Cmd+K to focus question input
      if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
        event.preventDefault();
        const questionInput = document.querySelector('textarea[placeholder*="Ask"]') as HTMLTextAreaElement;
        if (questionInput) {
          questionInput.focus();
        }
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

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
          {!hasWorkspaces && (
            <Card className="border-orange-200 bg-orange-50">
              <CardContent className="p-4">
                <div className="flex items-center space-x-3">
                  <Building2 className="h-5 w-5 text-orange-600" />
                  <div className="flex-1">
                    <p className="text-sm text-orange-800">
                      <strong>No Workspaces Connected:</strong> Connect a Slack workspace to start asking questions about your team's conversations.
                    </p>
                  </div>
                  <Button asChild size="sm" variant="outline">
                    <Link href="/dashboard/workspaces">
                      <Plus className="h-4 w-4 mr-2" />
                      Add Workspace
                    </Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
          
          {/* Question Input */}
          <QuestionInput
            onSubmit={handleAskQuestion}
            isLoading={askQuestionMutation.isPending}
            placeholder={hasWorkspaces ? "Ask a question about your Slack conversations..." : "Connect a workspace to start asking questions"}
            disabled={!hasWorkspaces}
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
                      Ask any question about your Slack conversations, team discussions, or uploaded documents.
                    </p>
                  </div>
                  {hasWorkspaces && (
                    <div className="text-sm text-gray-500 space-y-1">
                      <p><strong>Try asking:</strong></p>
                      <ul className="text-left space-y-1">
                        <li>• "What did we discuss about the new feature?"</li>
                        <li>• "Who mentioned the deployment issue?"</li>
                        <li>• "What are the latest updates on the project?"</li>
                        <li>• "Show me conversations about bug fixes"</li>
                      </ul>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}