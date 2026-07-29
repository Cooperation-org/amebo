'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient, type Goal } from '@/src/lib/api';
import { TaskSheet } from '@/src/components/work/TaskSheet';

/**
 * Goals — what amebo is working toward, and what it is waiting on.
 *
 * Obeys UX_PRINCIPLES.md. Every row opens into the same sheet the list uses, so
 * a goal's words are edited in place and it can be paused, completed or
 * cancelled from there. No separate edit screen.
 *
 * A goal with no trigger can never fire on its own. That is said on the row
 * rather than left to look merely idle.
 */

const LIVE = ['waiting_user', 'pending', 'active', 'paused'];

function tone(status: string) {
  if (status === 'waiting_user') return 'border-amber-200 bg-amber-50 text-amber-900';
  if (status === 'active') return 'border-emerald-200 bg-emerald-50 text-emerald-900';
  if (status === 'failed') return 'border-red-200 bg-red-50 text-red-900';
  return 'border-gray-200 bg-gray-100 text-gray-600';
}

function Row({ goal, onOpen }: { goal: Goal; onOpen: () => void }) {
  const trigger = (goal.trigger_config as { type?: string } | null)?.type;
  return (
    <div
      onClick={onOpen}
      className="cursor-pointer rounded-lg border bg-white px-4 py-3 hover:border-gray-300"
    >
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${tone(
            goal.status,
          )}`}
        >
          {goal.status.replace('_', ' ')}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] leading-snug text-gray-900">{goal.title}</p>
          <p className="mt-1 text-xs text-gray-400">
            {trigger ? trigger : <span className="text-amber-700">no trigger — cannot fire on its own</span>}
          </p>
        </div>
      </div>
    </div>
  );
}

export default function GoalsPage() {
  const { data, isLoading } = useQuery<Goal[]>({
    queryKey: ['goals', 'all'],
    queryFn: () => apiClient.getGoals(),
    staleTime: 30 * 1000,
  });
  const [open, setOpen] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);

  if (isLoading) return null;

  const goals = data ?? [];
  const live = goals.filter((g) => LIVE.includes(g.status));
  const done = goals.filter((g) => !LIVE.includes(g.status));

  if (goals.length === 0) {
    return <p className="text-sm text-gray-500">No goals yet.</p>;
  }

  return (
    <div className="space-y-2">
      <h1 className="sr-only">Goals</h1>
      {live.map((g) => (
        <Row key={g.id} goal={g} onOpen={() => setOpen(`goal:${g.id}`)} />
      ))}

      {done.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setShowDone((v) => !v)}
            className="flex w-full items-center gap-3 pt-6 pb-1 text-[11px] font-bold uppercase tracking-widest text-gray-400 hover:text-gray-600"
          >
            <span className="h-px flex-1 bg-gray-200" />
            {showDone ? 'hide' : `${done.length} done`}
            <span className="h-px flex-1 bg-gray-200" />
          </button>
          {showDone &&
            done.map((g) => (
              <Row key={g.id} goal={g} onOpen={() => setOpen(`goal:${g.id}`)} />
            ))}
        </>
      )}

      {open && <TaskSheet subject={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
