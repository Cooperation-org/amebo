'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ConfidenceBadge } from './ConfidenceBadge';
import { SourceCard } from './SourceCard';
import { Copy, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';

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

interface AnswerDisplayProps {
  response: QAResponse;
}

export function AnswerDisplay({ response }: AnswerDisplayProps) {
  const [showSources, setShowSources] = useState(true);
  
  const handleCopyAnswer = () => {
    navigator.clipboard.writeText(response.answer);
    toast.success('Answer copied to clipboard');
  };

  const formatProcessingTime = (ms?: number) => {
    if (!ms) return '';
    if (ms < 1000) return `${Math.round(ms)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div className="space-y-6">
      {/* Main Answer */}
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <div className="space-y-2">
              <CardTitle className="text-lg">Answer</CardTitle>
              <div className="flex items-center gap-2 flex-wrap">
                <ConfidenceBadge confidence={response.confidence} />
                {response.processing_time_ms && (
                  <span className="text-xs text-gray-500">
                    Answered in {formatProcessingTime(response.processing_time_ms)}
                  </span>
                )}
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={handleCopyAnswer}
              className="flex items-center gap-2"
            >
              <Copy className="h-4 w-4" />
              Copy
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="prose prose-sm max-w-none text-gray-800">
            <ReactMarkdown
              components={{
                p: ({ children }) => <p className="mb-4 leading-relaxed">{children}</p>,
                strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
                em: ({ children }) => <em className="italic">{children}</em>,
                ul: ({ children }) => <ul className="list-disc pl-6 mb-4 space-y-1">{children}</ul>,
                ol: ({ children }) => <ol className="list-decimal pl-6 mb-4 space-y-1">{children}</ol>,
                li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                h1: ({ children }) => <h1 className="text-xl font-bold mb-3 text-gray-900">{children}</h1>,
                h2: ({ children }) => <h2 className="text-lg font-semibold mb-2 text-gray-900">{children}</h2>,
                h3: ({ children }) => <h3 className="text-base font-medium mb-2 text-gray-900">{children}</h3>,
                code: ({ children }) => <code className="bg-gray-100 px-1 py-0.5 rounded text-sm font-mono">{children}</code>,
                pre: ({ children }) => <pre className="bg-gray-100 p-3 rounded-lg overflow-x-auto mb-4">{children}</pre>,
              }}
            >
              {response.answer}
            </ReactMarkdown>
          </div>
          
          {response.confidence_explanation && (
            <div className="mt-4 p-3 bg-blue-50 rounded-lg">
              <p className="text-sm text-blue-800">
                <strong>Confidence explanation:</strong> {response.confidence_explanation}
              </p>
            </div>
          )}
          
          {response.project_links && response.project_links.length > 0 && (
            <div className="mt-4">
              <h4 className="text-sm font-medium text-gray-700 mb-2">Related Links:</h4>
              <div className="space-y-2">
                {response.project_links.map((link, index) => (
                  <a
                    key={index}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {link.title} ({link.type})
                  </a>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Sources Section */}
      {response.sources && response.sources.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-900">
              Sources ({response.sources.length})
            </h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSources(!showSources)}
              className="flex items-center gap-2"
            >
              {showSources ? (
                <>
                  <ChevronUp className="h-4 w-4" />
                  Hide Sources
                </>
              ) : (
                <>
                  <ChevronDown className="h-4 w-4" />
                  Show Sources
                </>
              )}
            </Button>
          </div>
          
          {showSources && (
            <div className="grid gap-4">
              {response.sources.map((source, index) => (
                <SourceCard
                  key={index}
                  source={source}
                  index={index}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}