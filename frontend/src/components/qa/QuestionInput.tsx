'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Card, CardContent } from '@/components/ui/card';
import { Send, Loader2 } from 'lucide-react';

interface QuestionInputProps {
  onSubmit: (question: string) => void;
  isLoading?: boolean;
  placeholder?: string;
  disabled?: boolean;
}

export function QuestionInput({ 
  onSubmit, 
  isLoading = false, 
  placeholder = "Ask a question about your Slack conversations...",
  disabled = false
}: QuestionInputProps) {
  const [question, setQuestion] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (question.trim() && !isLoading && !disabled) {
      onSubmit(question.trim());
      setQuestion('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit(e);
    }
  };

  return (
    <Card>
      <CardContent className="p-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              className="min-h-[100px] resize-none"
              disabled={isLoading || disabled}
            />
            <div className="flex justify-between items-center text-sm text-gray-500">
              <span>Press Cmd+Enter to submit</span>
              <span>{question.length}/1000</span>
            </div>
          </div>
          <div className="flex justify-end">
            <Button 
              type="submit" 
              disabled={!question.trim() || isLoading || disabled}
              className="flex items-center gap-2"
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              {isLoading ? 'Searching...' : 'Ask Question'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}