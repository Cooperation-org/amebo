'use client';

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import {
  ChevronDown, ChevronRight, ChevronsDown, ChevronsUp, Clock, ExternalLink,
  MessageCircleQuestion, Pin, PinOff, Plus, Send, User,
} from 'lucide-react';
import { useWorkList, type WorkItem } from '@/src/hooks/useWorkList';
import { useWorkListLive } from '@/src/hooks/useWorkListLive';
import { useSayWhatsWrong } from '@/src/hooks/useSayWhatsWrong';
import { useEditWorkItem } from '@/src/hooks/useWorkItem';
import { useMarkWorkItem } from '@/src/hooks/useWorkListMark';
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
    <>
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
    </>
  );
}

/**
 * The controls on a row, on one line. They only exist while the pointer is on
 * the row; a strip of buttons printed on twenty rows is wallpaper.
 *
 * Every press stops here: the row itself opens the task on click.
 */
function Controls({ item, state = null }:
                  { item: WorkItem; state?: 'pinned' | 'buried' | null }) {
  return (
    <div
      className="mt-1.5 flex items-center gap-1 text-[11px] text-gray-400"
      onClick={(e) => e.stopPropagation()}
    >
      <Mark item={item} state={state} />
      {/* A follow-up's date lives in the CRM and there is no write path to it
          yet, so the contact card does not offer a control that would fail. Its
          own record is one click away on the row. */}
      {item.kind !== 'contact' && state !== 'buried' && <Snooze item={item} />}
    </div>
  );
}

/**
 * Pin the row above the list, or push it below it.
 *
 * Same shape as the push-out control beside it: quiet icons that appear when
 * you reach for the row, no words repeated twenty times down the page. Both
 * are one press each way — pin and unpin, bury and dig back up — with no
 * dialog in between, because the standard pattern for a reversible action is
 * to do it and offer undo rather than ask first.
 *
 * `state` is what this row already is, so the same control reads and reverses.
 */
function Mark({ item, state }: { item: WorkItem; state: 'pinned' | 'buried' | null }) {
  const mark = useMarkWorkItem();
  const press = (next: 'pinned' | 'buried' | null) => (e: React.MouseEvent) => {
    e.stopPropagation();
    mark.mutate({ subject: item.subject, state: next });
  };
  const button =
    'rounded p-1 opacity-0 transition-opacity hover:bg-gray-100 hover:text-gray-700 ' +
    'focus-visible:opacity-100 disabled:opacity-50 group-hover:opacity-100';

  if (state === 'pinned') {
    return (
      <button type="button" aria-label="Unpin this" disabled={mark.isPending}
              onClick={press(null)} className={`${button} opacity-100`}>
        <PinOff className="h-3.5 w-3.5" />
      </button>
    );
  }
  if (state === 'buried') {
    return (
      <button type="button" aria-label="Put this back on the list" disabled={mark.isPending}
              onClick={press(null)} className={`${button} opacity-100`}>
        <ChevronsUp className="h-3.5 w-3.5" />
      </button>
    );
  }
  return (
    <>
      <button type="button" aria-label="Pin this to the top" disabled={mark.isPending}
              onClick={press('pinned')} className={button}>
        <Pin className="h-3.5 w-3.5" />
      </button>
      <button type="button" aria-label="Push this down, off the list for now"
              disabled={mark.isPending} onClick={press('buried')} className={button}>
        <ChevronsDown className="h-3.5 w-3.5" />
      </button>
    </>
  );
}

function Row({ item, onOpen, state = null }:
             { item: WorkItem; onOpen: () => void; state?: 'pinned' | 'buried' | null }) {
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
      className={`group cursor-pointer rounded-lg border px-4 py-3 hover:border-gray-300 ${
        state === 'buried' ? 'bg-gray-50' : 'bg-white'
      }`}>
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
          <Controls item={item} state={state} />
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


/**
 * What this person pushed down.
 *
 * Burying is "not now", never "never", so it has to be somewhere they can find
 * and reverse — hidden with no way back would be a delete wearing a softer
 * word. A collapsed section with its count on the header is the standard
 * disclosure pattern (w3.org/WAI/ARIA/apg/patterns/disclosure), and it stays
 * shut until asked for so the page still reads as the list.
 *
 * A buried row digs itself back out on its own when its deadline comes within
 * two days. That is the server's doing; nothing here has to help.
 */
function Buried({ items, onOpen }: { items: WorkItem[]; onOpen: (s: string) => void }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="pt-6">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 text-[11px] font-bold uppercase tracking-widest text-gray-400 hover:text-gray-600"
      >
        <Chevron className="h-3.5 w-3.5" />
        pushed down ({items.length})
      </button>
      {open && (
        <div className="space-y-2 pt-2">
          {items.map((item) => (
            <Row key={item.subject} item={item} state="buried"
                 onOpen={() => onOpen(item.subject)} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Say what is wrong with the list, from the list.
 *
 * One line at the foot of the page rather than a control on every row: what is
 * wrong is as often about the list as about any one thing on it, and a button
 * repeated twenty times is wallpaper. Whatever row is open goes along with the
 * words, so two words are enough — "wrong person", "opens blank".
 *
 * It stays quiet until used. The placeholder is the whole instruction; a line
 * of prose explaining a text box is the product explaining itself.
 */
function WhatsWrong({ about }: { about: string | null }) {
  const [text, setText] = useState('');
  const say = useSayWhatsWrong();

  const send = () => {
    const said = text.trim();
    if (!said) return;
    say.mutate({ text: said, subject: about ?? undefined }, { onSuccess: () => setText('') });
  };

  return (
    <div className="pt-8">
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder={about ? "what's wrong with this one?" : "what's wrong?"}
          aria-label="Say what is wrong with the list"
          className="flex-1 rounded-md border bg-transparent px-3 py-2 text-sm placeholder:text-gray-400 focus:border-emerald-600 focus:bg-white focus:outline-none"
        />
        <button
          type="button"
          disabled={!text.trim() || say.isPending}
          onClick={send}
          className="rounded-md border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-40"
        >
          Say it
        </button>
      </div>
      {say.isError && (
        <p className="mt-1.5 text-xs text-red-800">
          {String((say.error as Error)?.message ?? 'That did not get filed.')}
        </p>
      )}
      {say.isSuccess && !text && (
        <p className="mt-1.5 text-xs text-gray-500">Filed on the {say.data.filed} board.</p>
      )}
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
  const pinned = data?.pinned ?? [];
  const buried = data?.buried ?? [];

  if (live.length === 0 && past.length === 0 && pinned.length === 0 && buried.length === 0) {
    // A team that just started has an empty board, and an empty page reads as
    // broken software. The way out of empty is a first task, so the page offers
    // that rather than explaining itself. Still offer the say-so too: "nothing
    // waiting on you" is itself sometimes the thing that is wrong, and there
    // would be nowhere to say it.
    return (
      <div>
        <p className="text-sm text-gray-500">Nothing waiting on you.</p>
        <Link
          href="/chat"
          className="mt-3 inline-flex items-center gap-2 rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700"
        >
          <Plus className="h-4 w-4" />
          Make a task
        </Link>
        <WhatsWrong about={null} />
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <h1 className="sr-only">Your list</h1>

      {/* Pinned first, in the order they were pinned. The server keeps these out
          of the cap, so a pin never costs one of the twenty. */}
      {pinned.map((item) => (
        <Row key={item.subject} item={item} state="pinned"
             onOpen={() => setOpen(item.subject)} />
      ))}
      {pinned.length > 0 && <div className="h-px bg-gray-200" />}

      {live.map((item) => (
        <Row key={item.subject} item={item} onOpen={() => setOpen(item.subject)} />
      ))}

      {/* A truncated list that looks complete is a lie about how much is
          waiting, so say the number. */}
      {(data?.live_total ?? 0) > live.length && (
        <p className="pt-1 text-xs text-gray-500">
          {live.length} of {data?.live_total}
        </p>
      )}

      {buried.length > 0 && <Buried items={buried} onOpen={setOpen} />}

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

      <WhatsWrong about={open} />

      {open && <TaskSheet subject={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
