'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronsDown, ChevronsUp } from 'lucide-react';
import { apiClient, type GoalMap, type GoalMapItem } from '@/src/lib/api';

/**
 * One goal as a map (backend/prompts/shapes/map.md), reviewed with the
 * review-as-a-human skill: one thing per line, a press per line, a question's
 * answer box beside it, nothing about the agent.
 */

const URL_RE = /(https?:\/\/[^\s<>"')\]]+)/g;
const short = (u: string) => u.replace(/^https?:\/\//, '').replace(/\/$/, '');

function Words({ text }: { text: string }) {
  return (
    <>
      {text.split(URL_RE).map((p, i) =>
        URL_RE.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
             className="text-emerald-700 hover:underline">{short(p).slice(0, 40)} ↗</a>
        ) : <span key={i}>{p}</span>,
      )}
    </>
  );
}

function AnswerBox({ goalId, item }: { goalId: string; item: GoalMapItem }) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const send = useMutation({
    mutationFn: () => apiClient.answerGoalMap(goalId, item.key, text.trim()),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goal-map', goalId] }),
  });
  return (
    <form onClick={(e) => e.stopPropagation()}
          onSubmit={(e) => { e.preventDefault(); if (text.trim()) send.mutate(); }}
          className="mt-2 flex gap-2 sm:mt-0 sm:w-72 sm:shrink-0">
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="answer" autoComplete="off"
             className="min-w-0 flex-1 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 focus:border-amber-500 focus:outline-none" />
      <button type="submit" disabled={!text.trim() || send.isPending}
              className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">
        {send.isPending ? '…' : 'ok'}
      </button>
    </form>
  );
}

function Line({ item, goalId }: { item: GoalMapItem; goalId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const mark = useMutation({
    mutationFn: (state: 'buried' | null) =>
      state ? apiClient.markWorkItem(item.subject, state) : apiClient.unmarkWorkItem(item.subject),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goal-map', goalId] }),
  });
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };
  const btn = 'rounded p-1.5 text-gray-300 hover:bg-gray-100 hover:text-gray-700';
  const hasDetail = !!item.detail;
  const control = item.state === 'buried' ? (
    <button className={btn} aria-label="bring back" onClick={stop(() => mark.mutate(null))}><ChevronsUp className="h-3.5 w-3.5" /></button>
  ) : (
    <button className={btn} aria-label="push down" onClick={stop(() => mark.mutate('buried'))}><ChevronsDown className="h-3.5 w-3.5" /></button>
  );
  return (
    <div onClick={() => hasDetail && setOpen((o) => !o)}
         className={`rounded-lg border bg-white px-3 py-2.5 ${item.ask ? 'border-amber-200' : ''} ${hasDetail ? 'cursor-pointer hover:border-gray-300' : ''} ${item.state === 'buried' ? 'opacity-60' : ''}`}>
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <p className="min-w-0 flex-1 text-[15px] leading-snug text-gray-900">
            {item.link ? (
              <a href={item.link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                 className="hover:underline">{item.line} <span className="text-emerald-700">↗</span></a>
            ) : item.line}
          </p>
          <span className="sm:hidden">{control}</span>
        </div>
        {item.ask && item.answer === null && <AnswerBox goalId={goalId} item={item} />}
        {item.answer !== null && <span className="text-sm text-gray-500">{item.answer}</span>}
        <span className="hidden sm:inline">{control}</span>
      </div>
      {open && hasDetail && (
        <div className="mt-2 whitespace-pre-line text-sm text-gray-700"><Words text={item.detail} /></div>
      )}
    </div>
  );
}

function Fold({ label, items, goalId }: { label: string; items: GoalMapItem[]; goalId: string }) {
  const [show, setShow] = useState(false);
  if (items.length === 0) return null;
  return (
    <div>
      <button onClick={() => setShow((s) => !s)} className="text-xs text-gray-400 hover:text-gray-700">
        {items.length} {label}
      </button>
      {show && <div className="mt-2 space-y-2">{items.map((it) => <Line key={it.key} item={it} goalId={goalId} />)}</div>}
    </div>
  );
}

export default function GoalMapPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isLoading, isError } = useQuery<GoalMap>({
    queryKey: ['goal-map', id],
    queryFn: () => apiClient.getGoalMap(id),
    enabled: !!id,
  });
  if (isLoading) return <div className="p-6 text-sm text-gray-400">…</div>;
  if (isError || !data) return <div className="p-6 text-sm text-red-700">not found</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-2 p-4 sm:p-6">
      {data.items.map((it) => <Line key={it.key} item={it} goalId={data.id} />)}
      {data.items.length === 0 && data.buried.length === 0 && data.answered.length === 0 && (
        <p className="whitespace-pre-line text-sm text-gray-600"><Words text={data.description ?? ''} /></p>
      )}
      <Fold label="answered" items={data.answered} goalId={data.id} />
      <Fold label="pushed down" items={data.buried} goalId={data.id} />
    </div>
  );
}
