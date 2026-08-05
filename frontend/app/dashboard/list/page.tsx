'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Clock, ExternalLink, MessageCircleQuestion, Send, User } from 'lucide-react';
import { useWorkList, type WorkItem } from '@/src/hooks/useWorkList';
import { useWorkListLive } from '@/src/hooks/useWorkListLive';
import { useEditWorkItem } from '@/src/hooks/useWorkItem';
import { TaskSheet } from '@/src/components/work/TaskSheet';
import { useOpenTask } from '@/src/hooks/useOpenTask';
import { apiClient } from '@/src/lib/api';
import { LATER_OPTIONS, inDays } from '@/src/lib/later';

/**
 * The claw list.
 *
 * What a row may contain, and nothing else: what a person said (with a way back
 * to where they said it), the thing itself, and links. No prose amebo wrote
 * about its own activity — if it did something useful the result is on the row,
 * not a report about it.
 *
 * One ranked list. A deadline raises rank rather than getting its own section.
 * What went past its date drops to the bottom and offers to be closed, so a
 * missed deadline is visible without nagging from the top.
 */

/**
 * What kind of card this is, when it is not the usual kind.
 *
 * Tasks are most of the list, so a task carries no marker: a symbol printed on
 * every row is wallpaper, not information — the same reason the push-out
 * control lost its words. The rows that are NOT board rows get one quiet icon,
 * which is the thing worth seeing at a glance: this one is a person, not a
 * ticket.
 */
function Kind({ kind }: { kind: WorkItem['kind'] }) {
  const marks = {
    contact: [User, 'a follow-up on a person, from the CRM'],
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

/** Red for the clock, blue for a judgement call — so you can see which is which. */
function Why({ label, kind }: { label: string; kind: string }) {
  const clock = kind === 'clock';
  return (
    <span
      className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider ${
        clock
          ? 'border-red-200 bg-red-50 text-red-800'
          : 'border-blue-200 bg-blue-50 text-blue-800'
      }`}
    >
      {label}
    </span>
  );
}

function Links({ item }: { item: WorkItem }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-gray-500">
      {item.links.map((l) => (
        <span key={l.url} className="inline-flex items-center">
          <a
            href={l.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 border-b border-emerald-200 text-emerald-800 hover:border-emerald-500"
          >
            {l.label}
            <ExternalLink className="h-3 w-3" />
          </a>
          {/* (?) marks a link amebo went and found, so you know which to distrust */}
          {l.found && (
            <span className="ml-1 font-mono text-gray-400" title="amebo found this, it was not on the record">
              (?)
            </span>
          )}
        </span>
      ))}
      {item.assignee && <span>· {item.assignee}</span>}
    </div>
  );
}

/**
 * Push the row out to a later day without opening it.
 *
 * One clock, no words. A word printed on every row is not a label, it is
 * wallpaper: twenty rows meant "snooze tomorrow in 3 days next week" eighty
 * times down the page. The standard row pattern is an icon that stays quiet
 * until you reach for it and opens its choices on press — Material's icon
 * button plus the ARIA menu-button pattern
 * (w3.org/WAI/ARIA/apg/patterns/menu-button). The dates only exist while one
 * row's menu is open, so no word is ever on screen twice.
 *
 * These sit inside a row that opens on click, so every press has to stop there.
 */
function Snooze({ item }: { item: WorkItem }) {
  const edit = useEditWorkItem();
  const [open, setOpen] = useState(false);

  return (
    <div
      className="mt-1.5 flex items-center gap-1 text-[11px] text-gray-400"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        aria-label="Push this out to a later day"
        aria-expanded={open}
        disabled={edit.isPending}
        onClick={() => setOpen((o) => !o)}
        className="rounded p-1 opacity-0 transition-opacity hover:bg-gray-100 hover:text-gray-700 focus-visible:opacity-100 disabled:opacity-50 group-hover:opacity-100"
      >
        <Clock className="h-3.5 w-3.5" />
      </button>
      {open &&
        LATER_OPTIONS.map(([label, n]) => (
          <button
            key={label}
            type="button"
            disabled={edit.isPending}
            onClick={() => {
              edit.mutate({ subject: item.subject, due_date: inDays(n) });
              setOpen(false);
            }}
            className="rounded px-1.5 py-0.5 hover:bg-gray-100 hover:text-gray-700 disabled:opacity-50"
          >
            {label}
          </button>
        ))}
      {edit.isError && <span className="text-red-700">didn&apos;t save</span>}
    </div>
  );
}

function Row({ item, onOpen }: { item: WorkItem; onOpen: () => void }) {
  // Fetch the task while the pointer is still on its way to the click, so the
  // sheet opens onto the record instead of onto a spinner.
  const qc = useQueryClient();
  const warm = () =>
    qc.prefetchQuery({
      queryKey: ['work-item', item.subject],
      queryFn: () => apiClient.getWorkItem(item.subject),
      staleTime: 15 * 1000,
    });

  return (
    <div
      onClick={onOpen}
      onPointerEnter={warm}
      onFocus={warm}
      className="group cursor-pointer rounded-lg border bg-white px-4 py-3 hover:border-gray-300">
      <div className="flex items-start gap-3">
        <Why label={item.reason.label} kind={item.reason.kind} />
        <Kind kind={item.kind} />
        <div className="min-w-0 flex-1">
          {item.quote ? (
            <p className="text-[15px] leading-snug text-gray-900">
              <span className="font-semibold">{item.quote.who}:</span> {item.quote.text}
            </p>
          ) : (
            <p className="text-[15px] leading-snug text-gray-900">{item.title}</p>
          )}
          <Links item={item} />
          {/* A follow-up's date lives in the CRM and there is no write path to
              it yet, so the contact card does not offer a control that would
              fail. Its own record is one click away on the row. */}
          {item.kind !== 'contact' && <Snooze item={item} />}
        </div>
      </div>
    </div>
  );
}

/** Past its date: still visible, still closable, no longer at the top. */
function PastRow({ item, onOpen }: { item: WorkItem; onOpen: () => void }) {
  return (
    <div
      onClick={onOpen}
      className="cursor-pointer rounded-lg border border-dashed bg-gray-50 px-4 py-3 hover:border-gray-400">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 rounded border bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-gray-500">
          {item.reason.label}
        </span>
        <Kind kind={item.kind} />
        <div className="min-w-0 flex-1">
          <p className="text-sm text-gray-700">{item.title}</p>
          <Links item={item} />
        </div>
      </div>
    </div>
  );
}

export default function WorkListPage() {
  const { data, isLoading, isError } = useWorkList();
  // Anything amebo changes shows up at once instead of on the next refresh.
  useWorkListLive();
  // Clicking anywhere on a row opens the whole task over the list.
  // The open task lives in the URL, so it can be shared and reloaded.
  const { open, setOpen } = useOpenTask();

  if (isLoading) return null;
  if (isError) {
    return <p className="text-sm text-gray-500">Can&apos;t reach the task source right now.</p>;
  }

  const live = data?.live ?? [];
  const past = data?.past ?? [];

  if (live.length === 0 && past.length === 0) {
    return <p className="text-sm text-gray-500">Nothing waiting on you.</p>;
  }

  return (
    <div className="space-y-2">
      <h1 className="sr-only">Your list</h1>
      {live.map((item) => (
        <Row key={item.subject} item={item} onOpen={() => setOpen(item.subject)} />
      ))}

      {past.length > 0 && (
        <>
          <div className="flex items-center gap-3 pt-6 pb-1 text-[11px] font-bold uppercase tracking-widest text-gray-400">
            <span className="h-px flex-1 bg-gray-200" />
            went past
            <span className="h-px flex-1 bg-gray-200" />
          </div>
          {past.map((item) => (
            <PastRow key={item.subject} item={item} onOpen={() => setOpen(item.subject)} />
          ))}
        </>
      )}

      {open && <TaskSheet subject={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
