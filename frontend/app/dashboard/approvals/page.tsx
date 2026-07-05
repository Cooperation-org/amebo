'use client';

import { Button } from '@/components/ui/button';
import { Check, X } from 'lucide-react';
import {
  usePendingActions,
  useApproveAction,
  useRejectAction,
  type PendingAction,
} from '@/src/hooks/usePendingActions';

function Row({ action }: { action: PendingAction }) {
  const approve = useApproveAction();
  const reject = useRejectAction();
  const busy = approve.isPending || reject.isPending;
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-white px-4 py-3">
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
      <Button size="sm" variant="outline" disabled={busy} onClick={() => reject.mutate(action.id)}>
        <X className="mr-1 h-4 w-4" /> Reject
      </Button>
    </div>
  );
}

/**
 * The approvals surface: every gated draft amebo is holding, one click to
 * approve (execute as amebo) or reject. This is THE human gate made visible.
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
