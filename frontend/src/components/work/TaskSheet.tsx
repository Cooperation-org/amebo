'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { useEditWorkItem, useWorkItem } from '@/src/hooks/useWorkItem';

/**
 * The task, opened over the list at nearly full size.
 *
 * Not a cramped strip inside the row and not a small modal: a cramped editor is
 * worse than a link out. Every field is edited where it sits and saves when you
 * leave it, so there is no edit mode and no Save button to hunt for. Esc closes.
 *
 * Underneath it is the thread — what people actually said, oldest first, with a
 * box to add to it.
 */

/** Saves on blur, only when the value actually changed. */
function Field({
  label,
  value,
  multiline,
  onSave,
  hint,
}: {
  label: string;
  value: string;
  multiline?: boolean;
  onSave: (v: string) => void;
  hint?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  const commit = () => {
    if (draft !== value) onSave(draft);
  };

  const shared =
    'w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm leading-relaxed text-gray-900 hover:border-gray-300 focus:border-emerald-600 focus:outline-none';

  return (
    <label className="block">
      <span className="mb-1.5 block text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
        {label}
        {hint && <span className="ml-1.5 font-medium normal-case tracking-normal text-emerald-700">{hint}</span>}
      </span>
      {multiline ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          rows={9}
          className={shared}
        />
      ) : (
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          className={shared}
        />
      )}
    </label>
  );
}

/** Later: pushes the task's own due date out. Nothing is stored in amebo. */
function Later({ onPick }: { onPick: (isoDate: string) => void }) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState('10');

  const inDays = (n: number) => {
    const d = new Date();
    d.setDate(d.getDate() + n);
    return d.toISOString().slice(0, 10);
  };

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100"
      >
        Later
      </button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border bg-white px-2.5 py-2 text-sm shadow-sm">
      <span className="px-1 text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
        new due date
      </span>
      {[
        ['tomorrow', 1],
        ['in 3 days', 3],
        ['next week', 7],
      ].map(([label, n]) => (
        <button
          key={label as string}
          type="button"
          onClick={() => onPick(inDays(n as number))}
          className="rounded-md px-2.5 py-1 text-gray-600 hover:bg-gray-100"
        >
          {label}
        </button>
      ))}
      <span className="flex items-center gap-1 px-1 text-gray-600">
        in
        <input
          value={days}
          onChange={(e) => setDays(e.target.value)}
          className="w-10 rounded border px-1 py-0.5 text-center"
        />
        <button
          type="button"
          onClick={() => onPick(inDays(parseInt(days, 10) || 1))}
          className="rounded-md px-2 py-1 hover:bg-gray-100"
        >
          days
        </button>
      </span>
    </div>
  );
}

export function TaskSheet({ subject, onClose }: { subject: string; onClose: () => void }) {
  const { data, isLoading } = useWorkItem(subject);
  const edit = useEditWorkItem();
  const [comment, setComment] = useState('');

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  const apply = (body: Parameters<typeof edit.mutate>[0]) => edit.mutate(body);

  return (
    <div className="fixed inset-0 z-50 bg-gray-900/25 p-3 sm:p-6" onClick={onClose}>
      <div
        className="mx-auto flex h-full max-w-5xl flex-col overflow-hidden rounded-xl border bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b bg-gray-50 px-5 py-3">
          <span className="font-mono text-xs font-bold">#{data?.ref ?? ''}</span>
          <span className="rounded bg-gray-200 px-2 py-0.5 text-[11px] text-gray-600">
            {data?.project ?? ''}
          </span>
          {data?.url && (
            <a
              href={data.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-xs text-emerald-800 hover:underline"
            >
              open in Taiga <ExternalLink className="h-3 w-3" />
            </a>
          )}
          <span className="ml-auto text-xs text-gray-400">
            {edit.isPending ? 'saving…' : 'saves as you leave a field'}
          </span>
          <button type="button" onClick={onClose} className="rounded p-1 hover:bg-gray-200">
            <X className="h-4 w-4" />
          </button>
        </div>

        {isLoading || !data ? (
          <div className="p-6 text-sm text-gray-400">…</div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto md:grid-cols-[1fr_300px]">
            <div className="space-y-4 p-5">
              <p className="text-lg font-semibold leading-snug">{data.title}</p>

              <Field
                label="Description"
                value={data.description ?? ''}
                multiline
                onSave={(v) => apply({ subject, description: v })}
              />

              {/* The thread: what people said, oldest first. */}
              <div>
                <p className="mb-1.5 text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
                  Thread
                </p>
                {data.comments.length === 0 ? (
                  <p className="text-sm text-gray-400">Nobody has said anything here.</p>
                ) : (
                  <ul className="space-y-2">
                    {data.comments.map((c, i) => (
                      <li key={i} className="text-sm leading-snug text-gray-800">
                        <span className="font-semibold">{c.who}:</span> {c.text}
                        {c.when && <span className="ml-2 font-mono text-[11px] text-gray-400">{c.when}</span>}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="mt-2 flex gap-2">
                  <input
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Add to the thread…"
                    className="flex-1 rounded-md border px-3 py-2 text-sm focus:border-emerald-600 focus:outline-none"
                  />
                  <button
                    type="button"
                    disabled={!comment.trim() || edit.isPending}
                    onClick={() => {
                      apply({ subject, comment: comment.trim() });
                      setComment('');
                    }}
                    className="rounded-md border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-40"
                  >
                    Post
                  </button>
                </div>
              </div>
            </div>

            <div className="space-y-4 border-t bg-gray-50/60 p-5 md:border-l md:border-t-0">
              <Field
                label="Due"
                value={data.due ?? ''}
                onSave={(v) => apply({ subject, due_date: v })}
              />
              <div>
                <p className="mb-1.5 text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
                  Status
                </p>
                <p className="text-sm text-gray-700">{data.status ?? '—'}</p>
              </div>
              <div>
                <p className="mb-1.5 text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
                  Assignee
                </p>
                <p className="text-sm text-gray-700">{data.assignee ?? 'no owner'}</p>
              </div>

              <div className="space-y-2 border-t pt-4">
                <button
                  type="button"
                  disabled={edit.isPending}
                  onClick={() => {
                    apply({ subject, close: true });
                    onClose();
                  }}
                  className="w-full rounded-md bg-emerald-800 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-900 disabled:opacity-50"
                >
                  Mark done
                </button>
                <Later
                  onPick={(iso) => {
                    apply({ subject, due_date: iso });
                    onClose();
                  }}
                />
              </div>

              {edit.isError && (
                <p className="text-xs text-red-700">
                  Taiga refused that change. Nothing was saved.
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
