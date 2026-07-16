'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Check, MessageSquare, X } from 'lucide-react';
import {
  usePendingActions,
  useApproveAction,
  useRejectAction,
  useFeedbackAction,
  type PendingAction,
} from '@/src/hooks/usePendingActions';

function Row({ action }: { action: PendingAction }) {
  const approve = useApproveAction();
  const reject = useRejectAction();
  const feedback = useFeedbackAction();
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackText, setFeedbackText] = useState('');
  const busy = approve.isPending || reject.isPending || feedback.isPending;

  const sendFeedback = () => {
    const text = feedbackText.trim();
    if (!text) return;
    feedback.mutate(
      { id: action.id, feedback: text },
      { onSuccess: () => setFeedbackOpen(false) },
    );
  };

  return (
    <div className="rounded-lg border bg-white px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-gray-900">{action.preview || `${action.action_type}: ${action.target ?? ''}`}</p>
          <p className="mt-0.5 text-xs text-gray-400">
            {action.action_type}
            {action.created_by ? ` · ${action.created_by}` : ''}
          </p>
          {action.error && <p className="mt-0.5 text-xs text-red-600">{action.error}</p>}
        </div>
        <Button size="sm" disabled={busy} onClick={() => approve.mutate(action.id)}>
          <Check className="mr-1 h-4 w-4" /> Approve
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => setFeedbackOpen((v) => !v)}
        >
          <MessageSquare className="mr-1 h-4 w-4" /> Feedback
        </Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => reject.mutate(action.id)}>
          <X className="mr-1 h-4 w-4" /> Reject
        </Button>
      </div>
      {feedbackOpen && (
        <div className="mt-2 flex items-end gap-2">
          <Textarea
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="What should change? Amebo revises the draft with this in view."
            className="min-h-[60px] flex-1 text-sm"
            maxLength={2000}
          />
          <Button size="sm" disabled={busy || !feedbackText.trim()} onClick={sendFeedback}>
            Send
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * The approvals surface: every gated draft amebo is holding. Approve executes
 * as amebo; reject is terminal; feedback declines THIS draft but re-arms the
 * goal with the human's words in view, so amebo redrafts instead of giving up.
 */
export default function ApprovalsPage() {
  const { data: actions, isLoading } = usePendingActions();
  if (isLoading) return null;
  if (!actions || actions.length === 0) {
    return <p className="text-sm text-gray-500">Nothing waiting for approval.</p>;
  }
  return (
    <div className="space-y-2">
      <h1 className="sr-only">Pending approvals</h1>
      {actions.map((a) => (
        <Row key={a.id} action={a} />
      ))}
    </div>
  );
}
