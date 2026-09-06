'use client';

import { useState, type DragEvent, type MouseEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Archive, ChevronsDown, ChevronsUp, Clock, Pin, PinOff, Send, User, MessageCircleQuestion,
} from 'lucide-react';
import { apiClient, type GoalProgress, type WorkItem, type WorkList } from '@/src/lib/api';
import { TaskSheet } from '@/src/components/work/TaskSheet';
import { useOpenTask } from '@/src/hooks/useOpenTask';
import { useEditWorkItem } from '@/src/hooks/useWorkItem';
import { useMarkWorkItem } from '@/src/hooks/useWorkListMark';
import { LATER_OPTIONS, inDays } from '@/src/lib/later';
import { useAuthStore } from '@/src/store/useAuthStore';

/**
 * The inbox — one screen: what is top for this person, then every live goal
 * and where it stands. UX_PRINCIPLES.md governs every line here:
 *
 * - Everything on a row can be acted on where it sits (4): pin, push down to
 *   backlog, later, archive; a person in the CRM opens Elm's drawer, which
 *   edits the record; a task opens its sheet with the board's own controls.
 * - Drag a row up or down: onto the pinned block pins it in that order (9, 12).
 * - Their words lead, with links clickable (3, 6).
 * - The list is pre-assembled and served at once; its age is on the page.
 */

const STATE: Record<GoalProgress['state'], { word: string; dot: string; bar: string }> = {
  waiting: { word: 'waiting on you', dot: 'bg-amber-500', bar: 'bg-amber-400' },
  stalled: { word: 'stalled', dot: 'bg-red-500', bar: 'bg-red-400' },
  moving: { word: 'moving', dot: 'bg-emerald-500', bar: 'bg-emerald-500' },
  paused: { word: 'paused', dot: 'bg-gray-400', bar: 'bg-gray-300' },
  done: { word: 'done', dot: 'bg-gray-300', bar: 'bg-gray-300' },
};

const URL_RE = /(https?:\/\/[^\s<>"')\]]+)/g;

/** A person's words with every URL in them clickable. */
function Words({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <>
      {parts.map((p, i) =>
        URL_RE.test(p) ? (
          <a
            key={i}
            href={p}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-emerald-700 hover:underline"
          >
            {p.replace(/^https?:\/\//, '').slice(0, 40)}
            {p.replace(/^https?:\/\//, '').length > 40 ? '…' : ''} ↗
          </a>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function Kind({ kind }: { kind: WorkItem['kind'] }) {
  const marks = {
    contact: [User, 'a person, in the CRM'],
    goal: [MessageCircleQuestion, 'a question amebo is holding for you'],
    draft: [Send, 'something amebo wants to send as you'],
  } as const;
  const mark = marks[kind as keyof typeof marks];
  if (!mark) return null;
  const [Icon, what] = mark;
  return (
    <span title={what} aria-label={what} className="mt-1 shrink-0 text-gray-400">
      <Icon className="h-3.5 w-3.5" />
    </span>
  );
}

const btn =
  'rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-800 disabled:opacity-40';

/** The four presses on every row. Each stops the click so the row does not open. */
function Controls({ item, state }: { item: WorkItem; state: 'pinned' | 'buried' | null }) {
  const mark = useMarkWorkItem();
  const edit = useEditWorkItem();
  const [later, setLater] = useState(false);
  const stop = (fn: () => void) => (e: MouseEvent) => {
    e.stopPropagation();
    fn();
  };
  const canEdit = item.kind === 'task' || item.kind === 'goal';
  return (
    <div className="flex shrink-0 items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
      {state === 'pinned' ? (
        <button type="button" title="unpin" className={btn} disabled={mark.isPending}
                onClick={stop(() => mark.mutate({ subject: item.subject, state: null }))}>
          <PinOff className="h-3.5 w-3.5" />
        </button>
      ) : state === 'buried' ? (
        <button type="button" title="back on the list" className={btn} disabled={mark.isPending}
                onClick={stop(() => mark.mutate({ subject: item.subject, state: null }))}>
          <ChevronsUp className="h-3.5 w-3.5" />
        </button>
      ) : (
        <>
          <button type="button" title="pin to the top" className={btn} disabled={mark.isPending}
                  onClick={stop(() => mark.mutate({ subject: item.subject, state: 'pinned' }))}>
            <Pin className="h-3.5 w-3.5" />
          </button>
          <button type="button" title="push down to backlog" className={btn} disabled={mark.isPending}
                  onClick={stop(() => mark.mutate({ subject: item.subject, state: 'buried' }))}>
            <ChevronsDown className="h-3.5 w-3.5" />
          </button>
        </>
      )}
      {canEdit && (
        <>
          <button type="button" title="later" className={btn} aria-expanded={later}
                  disabled={edit.isPending} onClick={stop(() => setLater((o) => !o))}>
            <Clock className="h-3.5 w-3.5" />
          </button>
          {later &&
            LATER_OPTIONS.map(([label, n]) => (
              <button key={label} type="button" disabled={edit.isPending}
                      className="rounded px-1.5 py-0.5 text-[11px] text-gray-600 hover:bg-gray-100"
                      onClick={stop(() => { edit.mutate({ subject: item.subject, due_date: inDays(n) }); setLater(false); })}>
                {label}
              </button>
            ))}
          <button type="button" title="archive" className={btn} disabled={edit.isPending}
                  onClick={stop(() => edit.mutate({ subject: item.subject, archive: true }))}>
            <Archive className="h-3.5 w-3.5" />
          </button>
        </>
      )}
    </div>
  );
}

type DragProps = {
  onDragStart: (e: DragEvent) => void;
  onDragOver: (e: DragEvent) => void;
  onDrop: (e: DragEvent) => void;
};

function Row({ item, state, onOpen, drag }:
             { item: WorkItem; state: 'pinned' | 'buried' | null; onOpen: () => void; drag: DragProps }) {
  const clock = item.reason.kind === 'clock';
  const first = item.links[0];
  if (item.kind === 'review') {
    return (
      <div className="rounded-lg border border-dashed bg-white px-4 py-3" draggable {...drag}>
        <div className="flex items-start gap-3">
          <p className="flex-1 text-[15px] leading-snug text-gray-700">{item.title}</p>
          <Controls item={item} state={state} />
        </div>
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
  return (
    <div
      onClick={onOpen}
      draggable
      {...drag}
      className={`flex cursor-pointer items-start gap-3 rounded-lg border bg-white px-4 py-3 hover:border-gray-300 ${
        state === 'buried' ? 'opacity-60' : ''
      }`}
    >
      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${clock ? 'bg-red-500' : 'bg-sky-500'}`} title={clock ? 'dated' : 'judgement'} />
      <Kind kind={item.kind} />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] leading-snug text-gray-900">{item.title}</p>
        <p className="mt-0.5 text-xs text-gray-500">
          {item.reason.label}
          {item.assignee ? ` · ${item.assignee}` : ''}
          {item.due ? ` · ${item.due}` : ''}
        </p>
        {item.quote && (
          <p className="mt-1 truncate text-sm text-gray-700" title={item.quote.text}>
            <span className="text-gray-400">{item.quote.who}: </span>
            {item.quote.text}
          </p>
        )}
      </div>
      {first && (
        <a href={first.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
           className="mt-0.5 shrink-0 text-xs text-emerald-700 hover:underline">
          {first.label.length > 22 ? first.label.slice(0, 22) + '…' : first.label} ↗
        </a>
      )}
      <Controls item={item} state={state} />
    </div>
  );
}

function GoalCard({ g, onOpen }: { g: GoalProgress; onOpen: () => void }) {
  const st = STATE[g.state] ?? STATE.moving;
  const total = g.tasks_open + g.tasks_done;
  const pct = total ? Math.round((g.tasks_done / total) * 100) : 0;
  return (
    <div onClick={onOpen} className="cursor-pointer rounded-lg border bg-white px-4 py-3 hover:border-gray-300">
      <div className="flex items-start gap-3">
        <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${st.dot}`} title={st.word} />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] leading-snug text-gray-900">{g.title}</p>
          <p className="mt-0.5 text-xs text-gray-500">
            {st.word}{g.owner ? ` · ${g.owner}` : ''}{g.org_label ? ` · ${g.org_label}` : ''}
            {g.quiet_days != null && g.quiet_days > 0 ? ` · quiet ${g.quiet_days}d` : ''}{g.kind === 'idea' ? ' · idea' : ''}
          </p>
          {g.state === 'waiting' && g.question && <p className="mt-1 text-sm text-amber-900">{g.question}</p>}
          {total > 0 && (
            <div className="mt-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded bg-gray-100">
                <div className={`h-full ${st.bar}`} style={{ width: `${pct}%` }} />
              </div>
              <a href={g.tasks_url ?? '#'} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                 className="shrink-0 font-mono text-[11px] text-gray-500 hover:underline">
                {g.tasks_done}/{total} tasks ↗
              </a>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ago(s: number) {
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

export default function InboxPage() {
  const { user } = useAuthStore();
  const admin = (user as { role?: string } | null)?.role === 'admin';
  const [as, setAs] = useState<string>('');
  const [q, setQ] = useState('');
  const team = useQuery({
    queryKey: ['team-members'],
    queryFn: async () => {
      const r = (await apiClient.getTeamMembers()) as any;
      const rows: any[] = Array.isArray(r) ? r : r?.members ?? [];
      return rows.map((m) => ({ email: String(m.email), name: String(m.name || m.full_name || m.email) }));
    },
    enabled: admin,
    staleTime: 600 * 1000,
  });
  const list = useQuery<WorkList>({
    queryKey: as ? ['work-list', 'as', as] : ['work-list'],
    queryFn: () => apiClient.getWorkList(as || undefined),
    staleTime: 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
  });
  const goals = useQuery({ queryKey: ['goals-progress'], queryFn: () => apiClient.getGoalsProgress(), staleTime: 60 * 1000 });
  const { open, setOpen } = useOpenTask();
  const [showAll, setShowAll] = useState(false);
  const mark = useMarkWorkItem();
  const [dragging, setDragging] = useState<string | null>(null);

  const data = list.data;
  const hit = (i: WorkItem) => {
    if (!q.trim()) return true;
    const t = q.toLowerCase();
    return [i.title, i.reason.label, i.assignee ?? '', i.quote?.text ?? '', i.quote?.who ?? '', ...i.links.map((l) => l.label)]
      .join(' ').toLowerCase().includes(t);
  };
  const searching = q.trim().length > 0;
  const pinned = (data?.pinned ?? []).filter(hit);
  const topN = data?.top_n ?? 5;
  const live = (data?.live ?? []).filter(hit);
  const shown = showAll || searching ? live : live.slice(0, Math.max(0, topN - Math.min(pinned.length, topN)));
  const buried = (data?.buried ?? []).filter(hit);
  const past = (data?.past ?? []).filter(hit);

  // Drag: dropping onto the pinned block (or onto a pinned row) pins the row
  // there; dropping a pinned row onto a live row unpins it. The pinned order is
  // the order of pinning, so re-pinning in sequence is the reorder.
  const dragFor = (subject: string, zone: 'pinned' | 'live'): DragProps => ({
    onDragStart: (e) => { setDragging(subject); e.dataTransfer.effectAllowed = 'move'; },
    onDragOver: (e) => { e.preventDefault(); },
    onDrop: (e) => {
      e.preventDefault();
      if (!dragging || dragging === subject) return;
      if (zone === 'pinned') {
        const order = pinned.map((p) => p.subject).filter((s) => s !== dragging);
        const at = order.indexOf(subject);
        order.splice(at < 0 ? order.length : at, 0, dragging);
        // re-pin in the chosen order; each press is one call, in sequence
        (async () => {
          for (const s of order) {
            await apiClient.clearWorkMark(s).catch(() => undefined);
            await apiClient.markWorkItem(s, 'pinned');
          }
          list.refetch();
        })();
      } else if (pinned.some((p) => p.subject === dragging)) {
        mark.mutate({ subject: dragging, state: null });
      }
      setDragging(null);
    },
  });

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
        <h2 className="flex items-baseline gap-2 text-[11px] font-bold uppercase tracking-widest text-gray-400">
          Top for you
          {data?.rubric?.[0] && (
            <span className="truncate normal-case tracking-normal" title={data.rubric.join('\n')}>· {data.rubric[0]}</span>
          )}
          {data && <span className="ml-auto shrink-0 font-normal normal-case tracking-normal">as of {ago(data.age_seconds)}</span>}
        </h2>
        <div className="flex items-center gap-2">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="search, including what you pushed down"
            className="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-3 py-1.5 text-sm focus:border-emerald-600 focus:outline-none"
          />
          {admin && (
            <select value={as} onChange={(e) => setAs(e.target.value)} title="see this page as someone else"
                    className="rounded-md border border-gray-200 bg-white px-2 py-1.5 text-sm text-gray-700">
              <option value="">as me</option>
              {(team.data ?? []).map((m) => <option key={m.email} value={m.email}>as {m.name}</option>)}
            </select>
          )}
        </div>
        {list.isLoading && <p className="text-sm text-gray-400">…</p>}
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); if (dragging && !pinned.some((p) => p.subject === dragging)) mark.mutate({ subject: dragging, state: 'pinned' }); setDragging(null); }}
          className={`space-y-2 rounded-lg ${dragging ? 'min-h-[2.5rem] border border-dashed border-gray-300 p-1' : ''}`}
        >
          {pinned.map((i) => (
            <Row key={i.subject} item={i} state="pinned" onOpen={() => setOpen(i.subject)} drag={dragFor(i.subject, 'pinned')} />
          ))}
          {dragging && pinned.length === 0 && <p className="px-2 text-[11px] text-gray-400">drop here to pin</p>}
        </div>
        {shown.map((i) => (
          <Row key={i.subject} item={i} state={null} onOpen={() => setOpen(i.subject)} drag={dragFor(i.subject, 'live')} />
        ))}
        {data && pinned.length + shown.length === 0 && <p className="text-sm text-gray-500">Nothing needs you.</p>}
        {data && !searching && live.length > shown.length && (
          <button type="button" onClick={() => setShowAll(true)} className="block pt-1 text-xs text-gray-500 hover:underline">
            all {data.live_total} →
          </button>
        )}
        {showAll && (
          <button type="button" onClick={() => setShowAll(false)} className="block pt-1 text-xs text-gray-500 hover:underline">← top only</button>
        )}
        {buried.length > 0 && (
          <details open={searching} className="pt-2 text-xs text-gray-500">
            <summary className="cursor-pointer">{buried.length} pushed down</summary>
            <div className="mt-2 space-y-1">
              {buried.map((i) => (
                <Row key={i.subject} item={i} state="buried" onOpen={() => setOpen(i.subject)} drag={dragFor(i.subject, 'live')} />
              ))}
            </div>
          </details>
        )}
        {(showAll || searching) && past.length > 0 && (
          <details open={searching} className="pt-2 text-xs text-gray-500">
            <summary className="cursor-pointer">{past.length} past their date</summary>
            <div className="mt-2 space-y-1">
              {past.map((i) => (
                <Row key={i.subject} item={i} state={null} onOpen={() => setOpen(i.subject)} drag={dragFor(i.subject, 'live')} />
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
                <span className={`h-2 w-2 rounded-full ${STATE[k].dot}`} />{counts[k]} {STATE[k].word}
              </span>
            ) : null,
          )}
        </h2>
        {gs.map((g) => <GoalCard key={g.id} g={g} onOpen={() => setOpen(`goal:${g.id}`)} />)}
        {goals.data && gs.length === 0 && <p className="text-sm text-gray-500">No live goals.</p>}
      </section>

      {open && <TaskSheet subject={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
