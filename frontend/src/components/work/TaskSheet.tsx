'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { useEditWorkItem, useWorkItem } from '@/src/hooks/useWorkItem';

/**
 * The task, opened over the list at nearly full size.
 *
 * UX PRINCIPLES — this file obeys them, and so must anything added to it:
 *
 *   SHOW, DON'T TELL          Show the thing. Never a report about it.
 *   EVERYTHING ACTIONABLE     Nothing on screen exists only to be read.
 *   LINKS                     If it cannot be shown, link it.
 *   SEE IT, EDIT IT           Every visible field is editable where it sits,
 *                             whenever the source system allows it at all.
 *   OMIT NEEDLESS WORDS       No labels that restate the obvious, no helper
 *                             prose, no AI voice.
 *   FEW CLICKS, SAVE IN FLOW  Edit in place, save on leaving the field.
 *   THEIR WORDS               A person's own words lead, attributed and linked.
 *
 * Not a cramped strip inside the row and not a small modal: a cramped editor is
 * worse than a link out. Esc closes.
 */

/**
 * Saves on blur, only when the value actually changed.
 *
 * Your words are never thrown away. Once edited, the field stops accepting
 * server values over the top of what you typed — a background refetch used to
 * overwrite unsaved text, so a failed save lost the words entirely. The draft
 * is released only after a save the server accepted.
 */
function Field({
  label,
  value,
  multiline,
  big,
  onSave,
  saveFailed,
  hint,
}: {
  label: string;
  value: string;
  multiline?: boolean;
  big?: boolean;
  onSave: (v: string) => void;
  saveFailed?: boolean;
  hint?: string;
}) {
  const [draft, setDraft] = useState(value);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    // Never clobber unsaved words with a value that arrived from the server.
    if (!dirty) setDraft(value);
  }, [value, dirty]);

  // The save landed: the server's value and the draft agree, so let go.
  useEffect(() => {
    if (dirty && value === draft) setDirty(false);
  }, [value, draft, dirty]);

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
        {dirty && (
          <span className="ml-1.5 font-medium normal-case tracking-normal text-amber-700">
            {saveFailed ? 'not saved — your words are still here' : 'unsaved'}
          </span>
        )}
      </span>
      {multiline ? (
        <textarea
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
          onBlur={commit}
          rows={9}
          className={shared}
        />
      ) : (
        <input
          value={draft}
          onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
          onBlur={commit}
          className={big ? `${shared} text-lg font-semibold` : shared}
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
  const { data, isLoading, isError, error } = useWorkItem(subject);
  const edit = useEditWorkItem();
  const [comment, setComment] = useState('');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, [onClose]);

  // A claw row can open AS the task it is holding (the server sends the task's
  // record with its own subject). Edits go to what is on screen, not to the row
  // that opened it — archive here archives the task.
  const target = data?.subject ?? subject;

  const apply = (body: Parameters<typeof edit.mutate>[0]) => edit.mutate(body);

  /** Fields already save on blur. This is for pressing something instead of
   *  trusting that: blur whatever has focus, then confirm briefly. */
  const saveNow = () => {
    (document.activeElement as HTMLElement | null)?.blur();
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

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

        {isError || (!isLoading && !data) ? (
          // Never a blank sheet: if it cannot load, say why and leave a way out.
          <div className="p-6 text-sm">
            <p className="text-red-800">
              {String((error as Error)?.message ?? "This didn't open.")}
            </p>
            <button
              type="button"
              onClick={onClose}
              className="mt-3 rounded-md border px-3 py-1.5 text-sm hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        ) : isLoading || !data ? (
          <div className="p-6 text-sm text-gray-400">…</div>
        ) : (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-0 overflow-y-auto md:grid-cols-[1fr_300px]">
            <div className="space-y-4 p-5">
              <Field
                label="Title"
                value={data.title}
                big
                saveFailed={edit.isError}
                onSave={(v) => apply({ subject: target, title: v })}
              />

              <Field
                label="Description"
                value={data.description ?? ''}
                multiline
                saveFailed={edit.isError}
                onSave={(v) => apply({ subject: target, description: v })}
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
                      apply({ subject: target, comment: comment.trim() });
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
                onSave={(v) => apply({ subject: target, due_date: v })}
              />
              {/* The board's own statuses, in board order — same as Marten. */}
              <label className="block">
                <span className="mb-1.5 block text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
                  Status
                </span>
                <select
                  value={data.status ?? ''}
                  onChange={(e) => apply({ subject: target, status: e.target.value })}
                  className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 hover:border-gray-300 focus:border-emerald-600 focus:outline-none"
                >
                  {!data.status && <option value="">—</option>}
                  {data.statuses.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              {data.kind === 'goal' && (
                <label className="block">
                  <span className="mb-1.5 block text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
                    Schedule
                  </span>
                  {/* Visible, therefore changeable. A goal with no schedule is
                      one-shot; a cron keeps returning until it is done. */}
                  <select
                    value={data.trigger ?? ''}
                    onChange={(e) => apply({ subject: target, trigger: e.target.value })}
                    className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 hover:border-gray-300 focus:border-emerald-600 focus:outline-none"
                  >
                    <option value="">once, then retire</option>
                    <option value="cron">daily until done</option>
                    <option value="manual">only when I say</option>
                  </select>
                </label>
              )}

              <label className="block">
                <span className="mb-1.5 block text-[10.5px] font-bold uppercase tracking-widest text-gray-400">
                  Assignee
                </span>
                <select
                  value={data.assignee ?? ''}
                  onChange={(e) => apply({ subject: target, assignee: e.target.value })}
                  className="w-full rounded-md border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 hover:border-gray-300 focus:border-emerald-600 focus:outline-none"
                >
                  {!data.assignee && <option value="">no owner</option>}
                  {data.members.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>

              <div className="space-y-2 border-t pt-4">
                <button
                  type="button"
                  disabled={edit.isPending}
                  onClick={() => {
                    apply({ subject: target, close: true });
                    onClose();
                  }}
                  className="w-full rounded-md bg-emerald-800 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-900 disabled:opacity-50"
                >
                  Mark done
                </button>
                <Later
                  onPick={(iso) => {
                    apply({ subject: target, due_date: iso });
                    onClose();
                  }}
                />

                {/* Fields save when you leave them; this is for when you would
                    rather press something than trust that. */}
                <button
                  type="button"
                  disabled={edit.isPending}
                  onClick={() => saveNow()}
                  className="w-full rounded-md border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
                >
                  {saved ? 'Saved' : 'Save'}
                </button>

                <div className="flex items-center gap-3 pt-1 text-xs text-gray-400">
                  <button
                    type="button"
                    disabled={edit.isPending}
                    onClick={() => {
                      apply({ subject: target, archive: true });
                      onClose();
                    }}
                    className="underline underline-offset-2 hover:text-gray-700"
                  >
                    archive
                  </button>
                  <button
                    type="button"
                    disabled={edit.isPending}
                    onClick={() => setConfirmDelete(true)}
                    className="underline underline-offset-2 hover:text-red-700"
                  >
                    delete
                  </button>
                </div>

                {confirmDelete && (
                  <div className="rounded-md border border-red-200 bg-red-50 p-3 text-xs text-red-900">
                    <p className="mb-2">Delete #{data.ref} for good? This cannot be undone.</p>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          apply({ subject: target, delete: true });
                          onClose();
                        }}
                        className="rounded bg-red-700 px-2.5 py-1 font-medium text-white hover:bg-red-800"
                      >
                        Delete it
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(false)}
                        className="rounded border border-red-200 bg-white px-2.5 py-1"
                      >
                        Keep it
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {edit.isError && (
                <p className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-900">
                  {String((edit.error as Error)?.message ?? '').includes('Blocked element')
                    ? 'This board is iceboxed in Taiga, so Taiga refuses every edit to it. Un-icebox the project there, then press Save.'
                    : String((edit.error as Error)?.message ?? 'That change did not save.')}
                  <br />
                  Nothing you typed was lost.
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
