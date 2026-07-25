'use client';

import { ExternalLink } from 'lucide-react';
import { useWorkList, type WorkItem } from '@/src/hooks/useWorkList';

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

function Row({ item }: { item: WorkItem }) {
  return (
    <div className="rounded-lg border bg-white px-4 py-3">
      <div className="flex items-start gap-3">
        <Why label={item.reason.label} kind={item.reason.kind} />
        <div className="min-w-0 flex-1">
          {item.quote ? (
            <p className="text-[15px] leading-snug text-gray-900">
              <span className="font-semibold">{item.quote.who}:</span> {item.quote.text}
            </p>
          ) : (
            <p className="text-[15px] leading-snug text-gray-900">{item.title}</p>
          )}
          <Links item={item} />
        </div>
      </div>
    </div>
  );
}

/** Past its date: still visible, still closable, no longer at the top. */
function PastRow({ item }: { item: WorkItem }) {
  return (
    <div className="rounded-lg border border-dashed bg-gray-50 px-4 py-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 shrink-0 rounded border bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider text-gray-500">
          {item.reason.label}
        </span>
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
        <Row key={item.subject} item={item} />
      ))}

      {past.length > 0 && (
        <>
          <div className="flex items-center gap-3 pt-6 pb-1 text-[11px] font-bold uppercase tracking-widest text-gray-400">
            <span className="h-px flex-1 bg-gray-200" />
            went past
            <span className="h-px flex-1 bg-gray-200" />
          </div>
          {past.map((item) => (
            <PastRow key={item.subject} item={item} />
          ))}
        </>
      )}
    </div>
  );
}
