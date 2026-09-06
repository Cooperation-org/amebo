'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient, type GoalProgress, type WorkItem } from '@/src/lib/api';
import { TaskSheet } from '@/src/components/work/TaskSheet';
import { useOpenTask } from '@/src/hooks/useOpenTask';

/**
 * The inbox — one screen: what is top for this person, then every live goal
 * and where it stands. Golda 2026-09-06: "the agent deals with the complexity and
 * crystallizes to the human the most important things, in few clear words,
 * concrete." Nothing amebo did is narrated here; only what needs a person and
 * how each goal is moving.
 *
 * Top rows come from the org rubric (`/api/work-list?limit=top`). Goal state is
 * a traffic light: amber waiting on a person, red stalled, green moving, grey
 * paused. The bar under a goal is its tasks done against open, read from the
 * board by the goal's tag.
 */

const STATE: Record<GoalProgress['state'], { word: string; dot: string; bar: string }> = {
  waiting: { word: 'waiting on you', dot: 'bg-amber-500', bar: 'bg-amber-400' },
  stalled: { word: 'stalled', dot: 'bg-red-500', bar: 'bg-red-400' },
  moving: { word: 'moving', dot: 'bg-emerald-500', bar: 'bg-emerald-500' },
  paused: { word: 'paused', dot: 'bg-gray-400', bar: 'bg-gray-300' },
  done: { word: 'done', dot: 'bg-gray-300', bar: 'bg-gray-300' },
};

function TopRow({ item, onOpen }: { item: WorkItem; onOpen: () => void }) {
  const clock = item.reason.kind === 'clock';
  const first = item.links[0];
  if (item.kind === 'review') {
    // The agent's finished work, folded: one row, every link, no sheet to open.
    return (
      <div className="rounded-lg border border-dashed bg-white px-4 py-3">
        <p className="text-[15px] leading-snug text-gray-700">{item.title}</p>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
          {item.links.map((l) => (
            <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="text-xs text-emerald-700 hover:underline">
              {l.label} ↗
            </a>
          ))}
        </div>
      </div>
    );
  }
  // A person in the CRM opens where the record is edited: Elm's lead drawer.
  // The amebo sheet has no write path to the CRM, and a pop-out you cannot act
  // on is a bug (UX_PRINCIPLES 4).
  const go = item.kind === 'contact' && first ? () => { window.location.href = first.url; } : onOpen;
  return (
    <div
      onClick={go}
      className="flex cursor-pointer items-start gap-3 rounded-lg border bg-white px-4 py-3 hover:border-gray-300"
    >
      <span
        className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${clock ? 'bg-red-500' : 'bg-sky-500'}`}
        title={clock ? 'dated' : 'judgement'}
      />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] leading-snug text-gray-900">{item.title}</p>
        <p className="mt-0.5 text-xs text-gray-500">
          {item.reason.label}
          {item.assignee ? ` · ${item.assignee}` : ''}
        </p>
        {item.quote && (
          <p className="mt-1 truncate text-sm text-gray-700">
            <span className="text-gray-400">{item.quote.who}: </span>
            {item.quote.text}
          </p>
        )}
      </div>
      {first && (
        <a
          href={first.url}
          target={item.kind === 'contact' ? undefined : '_blank'}
          rel="noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="shrink-0 text-xs text-emerald-700 hover:underline"
        >
          {first.label.length > 28 ? first.label.slice(0, 28) + '…' : first.label} ↗
        </a>
      )}
    </div>
  );
}

function GoalCard({ g, onOpen }: { g: GoalProgress; onOpen: () => void }) {
  const st = STATE[g.state] ?? STATE.moving;
  const total = g.tasks_open + g.tasks_done;
  const pct = total ? Math.round((g.tasks_done / total) * 100) : 0;
  return (
    <div
      onClick={onOpen}
      className="cursor-pointer rounded-lg border bg-white px-4 py-3 hover:border-gray-300"
    >
      <div className="flex items-start gap-3">
        <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${st.dot}`} title={st.word} />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] leading-snug text-gray-900">{g.title}</p>
          <p className="mt-0.5 text-xs text-gray-500">
            {st.word}
            {g.owner ? ` · ${g.owner}` : ''}
            {g.org_label ? ` · ${g.org_label}` : ''}
            {g.quiet_days != null && g.quiet_days > 0 ? ` · quiet ${g.quiet_days}d` : ''}
            {g.kind === 'idea' ? ' · idea' : ''}
          </p>
          {g.state === 'waiting' && g.question && (
            <p className="mt-1 text-sm text-amber-900">{g.question}</p>
          )}
          {total > 0 && (
            <div className="mt-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded bg-gray-100">
                <div className={`h-full ${st.bar}`} style={{ width: `${pct}%` }} />
              </div>
              <a
                href={g.tasks_url ?? '#'}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="shrink-0 font-mono text-[11px] text-gray-500 hover:underline"
              >
                {g.tasks_done}/{total} tasks ↗
              </a>
            </div>
          )}
          {total === 0 && g.state !== 'paused' && (
            <p className="mt-1 text-[11px] text-gray-400">no tasks yet</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function InboxPage() {
  const top = useQuery({
    queryKey: ['work-list-top'],
    queryFn: () => apiClient.getWorkListTop(),
    staleTime: 60 * 1000,
  });
  const goals = useQuery({
    queryKey: ['goals-progress'],
    queryFn: () => apiClient.getGoalsProgress(),
    staleTime: 60 * 1000,
  });
  const { open, setOpen } = useOpenTask();
  const [showAll, setShowAll] = useState(false);
  const all = useQuery({
    queryKey: ['work-list'],
    queryFn: () => apiClient.getWorkList(),
    staleTime: 60 * 1000,
    enabled: showAll,
  });

  const src = showAll && all.data ? all.data : top.data;
  const rows = [...(src?.pinned ?? []), ...(src?.live ?? [])];
  const gs = goals.data ?? [];
  const counts = {
    waiting: gs.filter((g) => g.state === 'waiting').length,
    stalled: gs.filter((g) => g.state === 'stalled').length,
    moving: gs.filter((g) => g.state === 'moving').length,
    paused: gs.filter((g) => g.state === 'paused').length,
  };

  return (
    <div className="space-y-8">
      <section className="space-y-2">
        <h2 className="text-[11px] font-bold uppercase tracking-widest text-gray-400">
          Top for you
          {top.data?.rubric?.[0] && (
            <span className="ml-2 normal-case tracking-normal text-gray-400" title={top.data.rubric.join('\n')}>
              · {top.data.rubric[0]}
            </span>
          )}
        </h2>
        {top.isLoading && <p className="text-sm text-gray-400">…</p>}
        {rows.map((i) => (
          <TopRow key={i.subject} item={i} onOpen={() => setOpen(i.subject)} />
        ))}
        {top.data && rows.length === 0 && (
          <p className="text-sm text-gray-500">Nothing needs you.</p>
        )}
        {top.data && top.data.live_total > rows.length && !showAll && (
          <button type="button" onClick={() => setShowAll(true)} className="block pt-1 text-xs text-gray-500 hover:underline">
            all {top.data.live_total} →
          </button>
        )}
        {showAll && (
          <button type="button" onClick={() => setShowAll(false)} className="block pt-1 text-xs text-gray-500 hover:underline">
            ← top only
          </button>
        )}
        {showAll && all.data && all.data.past.length > 0 && (
          <details className="pt-2 text-xs text-gray-500">
            <summary className="cursor-pointer">{all.data.past_total} past their date</summary>
            <div className="mt-2 space-y-1">
              {all.data.past.map((i) => (
                <TopRow key={i.subject} item={i} onOpen={() => setOpen(i.subject)} />
              ))}
            </div>
          </details>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="flex flex-wrap items-center gap-3 text-[11px] font-bold uppercase tracking-widest text-gray-400">
          Goals
          {(['waiting', 'stalled', 'moving', 'paused'] as const).map((k) =>
            counts[k] ? (
              <span key={k} className="flex items-center gap-1 normal-case tracking-normal">
                <span className={`h-2 w-2 rounded-full ${STATE[k].dot}`} />
                {counts[k]} {STATE[k].word}
              </span>
            ) : null,
          )}
        </h2>
        {goals.isLoading && <p className="text-sm text-gray-400">…</p>}
        {gs.map((g) => (
          <GoalCard key={g.id} g={g} onOpen={() => setOpen(`goal:${g.id}`)} />
        ))}
        {goals.data && gs.length === 0 && <p className="text-sm text-gray-500">No live goals.</p>}
      </section>

      {open && <TaskSheet subject={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
