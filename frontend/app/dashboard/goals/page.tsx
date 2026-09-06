'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type Goal } from '@/src/lib/api';
import { TaskSheet } from '@/src/components/work/TaskSheet';
import { Statements } from '@/src/components/goals/Statements';
import { useOpenTask } from '@/src/hooks/useOpenTask';

/**
 * Goals — what amebo is working toward, and what it is waiting on.
 *
 * Obeys UX_PRINCIPLES.md. Every row opens into the same sheet the list uses, so
 * a goal's words are edited in place and it can be paused, completed or
 * cancelled from there. No separate edit screen.
 *
 * States are colours, filters are one press, and a goal that is waiting on a
 * person shows its question on the row with a box to answer it there. Golda
 * (2026-09-06): "one time I might just want to filter all the ones that are
 * waiting for input and bam bam bam give them all input."
 *
 * A goal with no trigger can never fire on its own. That is said on the row
 * rather than left to look merely idle.
 */

// One state word per status, in the reader's terms. The colours are the
// traffic light: waiting on a person is the one that needs eyes.
const STATE: Record<string, { word: string; dot: string; chip: string }> = {
  waiting_user: { word: 'waiting on you', dot: 'bg-amber-500', chip: 'border-amber-300 bg-amber-50 text-amber-900' },
  active: { word: 'running', dot: 'bg-emerald-500', chip: 'border-emerald-300 bg-emerald-50 text-emerald-900' },
  pending: { word: 'queued', dot: 'bg-emerald-300', chip: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  paused: { word: 'paused', dot: 'bg-gray-400', chip: 'border-gray-300 bg-gray-100 text-gray-700' },
  failed: { word: 'failed', dot: 'bg-red-500', chip: 'border-red-300 bg-red-50 text-red-900' },
  completed: { word: 'done', dot: 'bg-gray-300', chip: 'border-gray-200 bg-white text-gray-500' },
};

const FILTERS: { key: string; label: string; statuses: string[] }[] = [
  { key: 'waiting', label: 'waiting on you', statuses: ['waiting_user'] },
  { key: 'running', label: 'running', statuses: ['active', 'pending'] },
  { key: 'paused', label: 'paused', statuses: ['paused', 'failed'] },
  { key: 'done', label: 'done', statuses: ['completed'] },
];

// Waiting first, then what is moving, then what stopped, then what finished.
const ORDER = ['waiting_user', 'active', 'pending', 'failed', 'paused', 'completed'];

function Answer({ goal }: { goal: Goal }) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const send = useMutation({
    mutationFn: () => apiClient.answerGoal(goal.id, text.trim()),
    onSuccess: () => {
      setText('');
      qc.invalidateQueries({ queryKey: ['goals'] });
    },
  });
  return (
    <form
      onClick={(e) => e.stopPropagation()}
      onSubmit={(e) => {
        e.preventDefault();
        if (text.trim()) send.mutate();
      }}
      className="mt-2 flex items-start gap-2"
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            if (text.trim()) send.mutate();
          }
        }}
        rows={1}
        placeholder="answer, then Enter"
        className="min-h-[36px] flex-1 resize-y rounded-md border border-amber-200 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-amber-500 focus:outline-none"
      />
      <button
        type="submit"
        disabled={!text.trim() || send.isPending}
        className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
      >
        {send.isPending ? '…' : 'send'}
      </button>
      {send.isError && <span className="text-xs text-red-700">did not send</span>}
    </form>
  );
}

function Row({ goal, onOpen }: { goal: Goal; onOpen: () => void }) {
  const trigger = (goal.trigger_config as { type?: string } | null)?.type;
  const st = STATE[goal.status] ?? { word: goal.status, dot: 'bg-gray-300', chip: '' };
  const waiting = goal.status === 'waiting_user';
  return (
    <div
      onClick={onOpen}
      className={`cursor-pointer rounded-lg border bg-white px-4 py-3 hover:border-gray-300 ${
        waiting ? 'border-amber-200' : ''
      }`}
    >
      <div className="flex items-start gap-3">
        <span
          className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${st.dot}`}
          title={st.word}
          aria-label={st.word}
        />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] leading-snug text-gray-900">{goal.title}</p>
          {waiting && goal.question && (
            <p className="mt-1 whitespace-pre-line text-sm text-amber-900">{goal.question}</p>
          )}
          {waiting && <Answer goal={goal} />}
          {!waiting && (
            <p className="mt-1 text-xs text-gray-400">
              {st.word}
              {trigger ? ` · ${trigger}` : ''}
              {!trigger && goal.status !== 'completed' && (
                <span className="text-amber-700"> · no trigger — cannot fire on its own</span>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function GoalsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['goals'],
    queryFn: () => apiClient.getGoals(),
    staleTime: 30 * 1000,
  });
  // The open task lives in the URL, so it can be shared and reloaded.
  const { open, setOpen } = useOpenTask();
  const [filter, setFilter] = useState<string | null>(null);
  if (isLoading) return null;
  const goals = [...(data ?? [])].sort(
    (a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status),
  );
  const counts = Object.fromEntries(
    FILTERS.map((f) => [f.key, goals.filter((g) => f.statuses.includes(g.status)).length]),
  );
  const active = FILTERS.find((f) => f.key === filter);
  const shown = active
    ? goals.filter((g) => active.statuses.includes(g.status))
    : goals.filter((g) => g.status !== 'completed');
  const done = goals.filter((g) => g.status === 'completed').length;

  return (
    <div className="space-y-2">
      <h1 className="sr-only">Goals</h1>
      {/* What the org is aiming at sits above what it is doing about it, and
          stays on screen when there are no goals yet — it is the thing you fill
          in first. */}
      <div className="mb-6">
        <Statements />
      </div>
      {/* The filters are the states, with counts, so the page says at a glance
          how many are waiting on a person before a single row is read. */}
      <div className="mb-3 flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const on = filter === f.key;
          const st = STATE[f.statuses[0]];
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(on ? null : f.key)}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                on ? st.chip : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${st.dot}`} />
              {f.label}
              <span className="font-mono text-[11px] opacity-70">{counts[f.key]}</span>
            </button>
          );
        })}
      </div>
      {goals.length === 0 && <p className="text-sm text-gray-500">No goals yet.</p>}
      {goals.length > 0 && shown.length === 0 && (
        <p className="text-sm text-gray-500">Nothing here.</p>
      )}
      {shown.map((g) => (
        <Row key={g.id} goal={g} onOpen={() => setOpen(`goal:${g.id}`)} />
      ))}
      {!active && done > 0 && (
        <button
          type="button"
          onClick={() => setFilter('done')}
          className="pt-4 text-[11px] font-bold uppercase tracking-widest text-gray-400 hover:text-gray-600"
        >
          {done} done
        </button>
      )}
      {open && <TaskSheet subject={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
