import { Badge } from '@/components/ui/badge';

interface ConfidenceBadgeProps {
  confidence: number;
  className?: string;
}

export function ConfidenceBadge({ confidence, className }: ConfidenceBadgeProps) {
  const getConfidenceColor = (score: number) => {
    if (score >= 80) return 'bg-green-100 text-green-800 border-green-200';
    if (score >= 60) return 'bg-yellow-100 text-yellow-800 border-yellow-200';
    if (score >= 40) return 'bg-orange-100 text-orange-800 border-orange-200';
    return 'bg-red-100 text-red-800 border-red-200';
  };

  const getConfidenceLabel = (score: number) => {
    if (score >= 80) return 'High Confidence';
    if (score >= 60) return 'Medium Confidence';
    if (score >= 40) return 'Low Confidence';
    return 'Very Low Confidence';
  };

  return (
    <Badge 
      variant="outline" 
      className={`${getConfidenceColor(confidence)} ${className}`}
    >
      {getConfidenceLabel(confidence)} ({confidence}%)
    </Badge>
  );
}