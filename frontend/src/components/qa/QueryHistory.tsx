'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ConfidenceBadge } from './ConfidenceBadge';
import { Clock, Trash2, RotateCcw } from 'lucide-react';
import { useQueryHistory, useSaveQueryHistory } from '@/src/hooks/useQA';

interface QueryHistoryProps {
  onSelectQuery: (question: string) => void;
}

export function QueryHistory({ onSelectQuery }: QueryHistoryProps) {
  const { data: history = [], isLoading } = useQueryHistory();
  const saveHistory = useSaveQueryHistory();

  const handleClearHistory = () => {
    saveHistory([]);
  };

  const handleDeleteQuery = (id: string) => {
    const newHistory = history.filter((item: any) => item.id !== id);
    saveHistory(newHistory);
  };

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / (1000 * 60));
      const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
      const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      
      return date.toLocaleDateString();
    } catch {
      return timestamp;
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-6">
          <div className="animate-pulse space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 bg-gray-200 rounded"></div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <Clock className="h-4 w-4" />
            Recent Questions
          </CardTitle>
          {history.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearHistory}
              className="h-8 px-2"
            >
              <Trash2 className="h-3 w-3" />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {history.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <Clock className="h-8 w-8 mx-auto mb-2 text-gray-400" />
            <p className="text-sm">No recent questions</p>
            <p className="text-xs text-gray-400 mt-1">
              Your question history will appear here
            </p>
          </div>
        ) : (
          <div className="space-y-3 max-h-96 overflow-y-auto">
            {history.map((item: any) => (
              <div
                key={item.id}
                className="p-3 border rounded-lg hover:bg-gray-50 transition-colors group"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <button
                      onClick={() => onSelectQuery(item.question)}
                      className="text-left w-full"
                    >
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {item.question}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <ConfidenceBadge 
                          confidence={item.confidence} 
                          className="text-xs"
                        />
                        <span className="text-xs text-gray-500">
                          {formatTimestamp(item.timestamp)}
                        </span>
                      </div>
                    </button>
                  </div>
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onSelectQuery(item.question)}
                      className="h-6 w-6 p-0"
                    >
                      <RotateCcw className="h-3 w-3" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDeleteQuery(item.id)}
                      className="h-6 w-6 p-0 text-red-600 hover:text-red-700"
                    >
                      <Trash2 className="h-3 w-3" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}