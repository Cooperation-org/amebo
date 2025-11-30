import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { MessageSquare, FileText, ExternalLink, Copy } from 'lucide-react';
import { toast } from 'sonner';

interface QASource {
  source_type: string;
  text: string;
  metadata: {
    channel_name?: string;
    user_name?: string;
    timestamp?: string;
    message_link?: string;
    file_name?: string;
    document_title?: string;
  };
  relevance_score?: number;
}

interface SourceCardProps {
  source: QASource;
  index: number;
}

export function SourceCard({ source, index }: SourceCardProps) {
  const isSlackMessage = source.source_type === 'slack_message';
  
  const handleCopyText = () => {
    navigator.clipboard.writeText(source.text);
    toast.success('Text copied to clipboard');
  };

  const formatTimestamp = (timestamp?: string) => {
    if (!timestamp) return '';
    try {
      return new Date(timestamp).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return timestamp;
    }
  };

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {isSlackMessage ? (
              <MessageSquare className="h-4 w-4 text-blue-600" />
            ) : (
              <FileText className="h-4 w-4 text-green-600" />
            )}
            <Badge variant="outline" className="text-xs">
              Source {index + 1}
            </Badge>
            {source.relevance_score && (
              <Badge variant="secondary" className="text-xs">
                {Math.round(source.relevance_score * 100)}% match
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={handleCopyText}
              className="h-8 w-8 p-0"
            >
              <Copy className="h-3 w-3" />
            </Button>
            {source.metadata.message_link && (
              <Button
                variant="ghost"
                size="sm"
                asChild
                className="h-8 w-8 p-0"
              >
                <a 
                  href={source.metadata.message_link} 
                  target="_blank" 
                  rel="noopener noreferrer"
                >
                  <ExternalLink className="h-3 w-3" />
                </a>
              </Button>
            )}
          </div>
        </div>
        
        <div className="text-sm text-gray-600">
          {isSlackMessage ? (
            <div className="flex items-center gap-2 flex-wrap">
              {source.metadata.channel_name && (
                <span>#{source.metadata.channel_name}</span>
              )}
              {source.metadata.user_name && (
                <span>by {source.metadata.user_name}</span>
              )}
              {source.metadata.timestamp && (
                <span>{formatTimestamp(source.metadata.timestamp)}</span>
              )}
            </div>
          ) : (
            <div>
              {source.metadata.document_title || source.metadata.file_name || 'Document'}
            </div>
          )}
        </div>
      </CardHeader>
      
      <CardContent className="pt-0">
        <div className="text-sm text-gray-800 leading-relaxed">
          {source.text.length > 300 ? (
            <details className="group">
              <summary className="cursor-pointer text-blue-600 hover:text-blue-800">
                {source.text.substring(0, 300)}...
                <span className="ml-1 group-open:hidden">Show more</span>
                <span className="ml-1 hidden group-open:inline">Show less</span>
              </summary>
              <div className="mt-2">
                {source.text.substring(300)}
              </div>
            </details>
          ) : (
            source.text
          )}
        </div>
      </CardContent>
    </Card>
  );
}