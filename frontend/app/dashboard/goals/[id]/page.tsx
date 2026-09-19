'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronsDown, ChevronsUp, Pin, PinOff } from 'lucide-react';
import { apiClient, type GoalMap, type GoalMapItem } from '@/src/lib/api';

/**
 * One goal as a map (backend/prompts/shapes/map.md). The top layer is one line
 * per thing; a line opens in place to its detail; pin keeps it on top, bury
 * pushes it down and it stays down. UX_PRINCIPLES.md: their words, links
 * clickable, nothing about the agent, no labels that explain the UI.
 */

const URL_RE = /(https?:\/\/[^\s<>"')\]]+)/g;

function Words({ text }: { text: string }) {
  return (
    <>
      {text.split(URL_RE).map((p, i) =>
        URL_RE.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
             className="text-emerald-700 hover:underline break-all">
            {p.replace(/^https?:\/\//, '').slice(0, 48)}{p.replace(/^https?:\/\//, '').length > 48 ? '…' : ''} ↗
          </a>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function Line({ item, goalId }: { item: GoalMapItem; goalId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const mark = useMutation({
    mutationFn: (state: 'pinned' | 'buried' | null) =>
      state ? apiClient.markWorkItem(item.subject, state) : apiClient.unmarkWorkItem(item.subject),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['goal-map', goalId] }),
  });
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn(); };
  const btn = 'rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-700';
  return (
    <div onClick={() => setOpen((o) => !o)}
         className={`group cursor-pointer rounded-lg border bg-white px-4 py-2.5 hover:border-gray-300 ${item.state === 'buried' ? 'opacity-60' : ''}`}>
      <div className="flex items-start gap-2">
        <p className="min-w-0 flex-1 text-[15px] leading-snug text-gray-900">
          <Words text={item.line} />
          {item.link && !item.line.includes(item.link) && (
            <> <a href={item.link} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                  className="text-emerald-700 hover:underline">↗</a></>
          )}
        </p>
        <div className="flex shrink-0 gap-0.5 opacity-0 group-hover:opacity-100">
          {item.state === 'pinned' ? (
            <button className={btn} title="unpin" onClick={stop(() => mark.mutate(null))}><PinOff className="h-3.5 w-3.5" /></button>
          ) : item.state === 'buried' ? (
            <button className={btn} title="bring back" onClick={stop(() => mark.mutate(null))}><ChevronsUp className="h-3.5 w-3.5" /></button>
          ) : (
            <>
              <button className={btn} title="pin" onClick={stop(() => mark.mutate('pinned'))}><Pin className="h-3.5 w-3.5" /></button>
              <button className={btn} title="push down, stays down" onClick={stop(() => mark.mutate('buried'))}><ChevronsDown className="h-3.5 w-3.5" /></button>
            </>
          )}
        </div>
      </div>
      {open && (item.detail || item.source) && (
        <div className="mt-2 whitespace-pre-line text-sm text-gray-700">
          <Words text={item.detail} />
          {item.source && <p className="mt-1 text-xs text-gray-400"><Words text={item.source} /></p>}
        </div>
      )}
    </div>
  );
}

function Answer({ goalId }: { goalId: string }) {
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const send = useMutation({
    mutationFn: () => apiClient.answerGoal(goalId, text.trim()),
    onSuccess: () => { setText(''); qc.invalidateQueries({ queryKey: ['goal-map', goalId] }); },
  });
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (text.trim()) send.mutate(); }} className="mt-2 flex items-start gap-2">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="answer"
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (text.trim()) send.mutate(); } }}
                className="min-h-[36px] flex-1 resize-y rounded-md border border-amber-200 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-amber-500 focus:outline-none" />
      <button type="submit" disabled={!text.trim() || send.isPending}
              className="rounded-md bg-amber-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40">
        {send.isPending ? '…' : 'send'}
      </button>
    </form>
  );
}

export default function GoalMapPage() {
  const { id } = useParams<{ id: string }>();
  const [showBuried, setShowBuried] = useState(false);
  const [showRuns, setShowRuns] = useState(false);
  const { data, isLoading, isError } = useQuery<GoalMap>({
    queryKey: ['goal-map', id],
    queryFn: () => apiClient.getGoalMap(id),
    enabled: !!id,
  });
  if (isLoading) return <div className="p-6 text-sm text-gray-400">…</div>;
  if (isError || !data) return <div className="p-6 text-sm text-red-700">not found</div>;

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4 sm:p-6">
      <h1 className="text-lg font-semibold leading-snug text-gray-900">{data.title}</h1>

      {data.question && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
          <p className="whitespace-pre-line text-sm text-amber-900"><Words text={data.question} /></p>
          <Answer goalId={data.id} />
        </div>
      )}

      {data.items.map((it) => <Line key={it.key} item={it} goalId={data.id} />)}

      {data.items.length === 0 && data.buried.length === 0 && data.description && (
        <p className="whitespace-pre-line text-sm text-gray-600"><Words text={data.description} /></p>
      )}

      {data.buried.length > 0 && (
        <div>
          <button onClick={() => setShowBuried((s) => !s)} className="text-xs text-gray-400 hover:text-gray-700">
            {showBuried ? 'hide' : `${data.buried.length} pushed down`}
          </button>
          {showBuried && <div className="mt-2 space-y-2">{data.buried.map((it) => <Line key={it.key} item={it} goalId={data.id} />)}</div>}
        </div>
      )}

      {data.runs.length > 0 && (
        <div>
          <button onClick={() => setShowRuns((s) => !s)} className="text-xs text-gray-400 hover:text-gray-700">
            {showRuns ? 'hide runs' : `${data.runs.length} runs`}
          </button>
          {showRuns && (
            <ul className="mt-2 space-y-1 text-xs text-gray-500">
              {data.runs.map((r, i) => (
                <li key={i}><span className="text-gray-400">{r.at.slice(0, 16).replace('T', ' ')}</span> · <Words text={r.line} /></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
