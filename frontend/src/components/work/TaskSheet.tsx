'use client';

import { useEffect, useState } from 'react';
import { ExternalLink, X } from 'lucide-react';
import { useEditWorkItem, useWorkItem } from '@/src/hooks/useWorkItem';
import type { WorkItemDetail } from '@/src/lib/api';
import { LATER_OPTIONS, inDays } from '@/src/lib/later';

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
      {LATER_OPTIONS.map(([label, n]) => (
        <button
          key={label}
          type="button"
          onClick={() => onPick(inDays(n))}
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

  // `rowSubject` is how the list knows which row to drop when these two differ.
  const apply = (body: Parameters<typeof edit.mutate>[0]) =>
    edit.mutate({ ...body, rowSubject: subject });

  /** For the ones that end the item: the sheet stays up until the server has
   *  actually agreed, so a refusal is read on screen instead of vanishing with
   *  the sheet. The row itself already left the list the moment it was pressed. */
  const applyAndClose = (body: Parameters<typeof edit.mutate>[0]) =>
    edit.mutate({ ...body, rowSubject: subject }, { onSuccess: () => onClose() });

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
          {!!data?.code && <span className="font-mono text-xs font-bold">{data.code}</span>}
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
              {/* Never "open in Taiga": the URL is Marten's and always was, and
                  the label was pointing people at an interface we do not use. */}
              {data?.kind === 'contact' ? 'open in the CRM' : 'open on the board'}{' '}
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {/* Only while it is actually happening. A permanent line telling you
              how saving works is the product explaining itself, which every
              guideline (and Golda) says not to do. */}
          <span className="ml-auto text-xs text-gray-400">
            {edit.isPending ? 'saving…' : ''}
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
        ) : data.kind === 'draft' ? (
          /* A draft is words amebo wants to send in your name, so the words are
             the whole sheet. Saying what is wrong with it hands it back to the
             claw to write again; sending it lives on the approvals surface,
             where the audit trail is, and is never a side effect here. */
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
            <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-gray-900">
              {data.description}
            </p>
            <div className="flex gap-2 border-t pt-4">
              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="What should it say instead?"
                rows={6}
                className="flex-1 resize-y rounded-md border px-3 py-2 text-sm leading-relaxed focus:border-emerald-600 focus:outline-none"
              />
              <button
                type="button"
                disabled={!comment.trim() || edit.isPending}
                onClick={() => {
                  applyAndClose({ subject: target, comment: comment.trim() });
                  setComment('');
                }}
                className="rounded-md bg-emerald-800 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-900 disabled:opacity-40"
              >
                Write it again
              </button>
              <button
                type="button"
                disabled={edit.isPending}
                onClick={() => applyAndClose({ subject: target, archive: true })}
                className="rounded-md border px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50"
              >
                Drop it
              </button>
            </div>
            {edit.isError && (
              <p className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-900">
                {String((edit.error as Error)?.message ?? 'That did not go through.')}
              </p>
            )}
          </div>
        ) : data.kind === 'contact' ? (
          /* A person in the CRM, doable from here: the one next step (edit it
             where it sits, replaced not appended), done in one press, their
             last words with links live, and a box to log what you did. Writes
             go straight to the CRM record — its home (UX_PRINCIPLES 4, 5). */
          <ContactSheet data={data} apply={apply} pending={edit.isPending} />
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
                  {/* Room to say something. A one-line box says a one-line
                      answer is what is wanted, and a comment here is often the
                      instruction someone is handing the claw. */}
                  <textarea
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Add to the thread…"
                    rows={6}
                    className="flex-1 resize-y rounded-md border px-3 py-2 text-sm leading-relaxed focus:border-emerald-600 focus:outline-none"
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
                  <button
                    type="button"
                    disabled={edit.isPending}
                    onClick={() => apply({ subject: target, run_now: true })}
                    className="mt-2 w-full rounded-md bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
                  >
                    ▶ run now
                  </button>
                  {(data.runs ?? []).length > 0 && (
                    <ul className="mt-3 space-y-2">
                      {(data.runs ?? []).map((r, i) => (
                        <li key={i} className="text-xs text-gray-700">
                          <span className="font-mono text-gray-500">{r.when}</span>{' '}
                          <span className={r.outcome === 'failed' ? 'text-red-700' : r.outcome === 'running' ? 'text-amber-700' : 'text-emerald-800'}>{r.outcome}</span>
                          {r.tools.length > 0 && <span className="text-gray-400"> · {r.tools.join(', ')}</span>}
                          {r.summary && <p className="mt-0.5 whitespace-pre-wrap text-gray-800"><Linked text={r.summary} /></p>}
                        </li>
                      ))}
                    </ul>
                  )}
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
                    onClick={() => applyAndClose({ subject: target, archive: true })}
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
                        onClick={() => applyAndClose({ subject: target, delete: true })}
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


const URL_RE = /(https?:\/\/[^\s<>"')\]]+)/g;
function Linked({ text }: { text: string }) {
  return (
    <>
      {text.split(URL_RE).map((p, i) =>
        /^https?:\/\//.test(p) ? (
          <a key={i} href={p} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">
            {p.replace(/^https?:\/\//, '').slice(0, 48)} ↗
          </a>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function ContactSheet({ data, apply, pending }:
                      { data: WorkItemDetail; apply: (b: any) => void; pending: boolean }) {
  const [summary, setSummary] = useState(data.next?.summary ?? '');
  const [due, setDue] = useState(data.next?.due ?? '');
  const [note, setNote] = useState('');
  const [all, setAll] = useState(false);
  const [more, setMore] = useState(false);
  const thread = all ? data.comments : data.comments.slice(0, 3);
  const saveNext = () => {
    if (summary.trim() === (data.next?.summary ?? '') && (due || '') === (data.next?.due ?? '')) return;
    apply({ subject: data.subject, title: summary.trim() || undefined, due_date: due || undefined });
  };
  return (
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
      <div>
        <p className="text-[17px] font-semibold leading-snug text-gray-900">{data.title}</p>
        <p className="mt-0.5 text-xs text-gray-500">
          {[data.code, data.assignee].filter(Boolean).join(' · ')}
        </p>
        {(data.links ?? []).length > 0 && (
          <p className="mt-1 flex flex-wrap gap-x-3 text-xs">
            {(data.links ?? []).map((l) => (
              <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">{l.label} ↗</a>
            ))}
          </p>
        )}
      </div>

      {data.description && (
        <div className={`text-sm leading-relaxed text-gray-800 ${more ? '' : 'line-clamp-4'}`}>
          <Linked text={data.description} />
        </div>
      )}
      {data.description && data.description.length > 280 && (
        <button type="button" onClick={() => setMore((v) => !v)} className="-mt-3 text-xs text-gray-500 hover:underline">
          {more ? 'less' : 'more'}
        </button>
      )}

      <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
        <p className="mb-1.5 text-[10.5px] font-bold uppercase tracking-widest text-amber-800">Next</p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            onBlur={saveNext}
            onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
            placeholder="what to do next"
            className="min-w-[12rem] flex-1 rounded-md border border-amber-200 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-amber-500 focus:outline-none"
          />
          <input
            type="date"
            value={due}
            onChange={(e) => setDue(e.target.value)}
            onBlur={saveNext}
            className="rounded-md border border-amber-200 bg-white px-2 py-1.5 text-sm text-gray-900"
          />
          {data.next?.activity_id && (
            <button
              type="button"
              disabled={pending}
              onClick={() => apply({ subject: data.subject, close: true, comment: note.trim() || undefined })}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
              title="done — logs it on the record"
            >
              done ✓
            </button>
          )}
        </div>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (note.trim()) { apply({ subject: data.subject, comment: note.trim() }); setNote(''); }
        }}
        className="flex items-start gap-2"
      >
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); (e.currentTarget.form as HTMLFormElement).requestSubmit(); } }}
          rows={1}
          placeholder="what happened, in your words"
          className="min-h-[36px] flex-1 resize-y rounded-md border border-gray-200 px-3 py-1.5 text-sm focus:border-emerald-600 focus:outline-none"
        />
        <button type="submit" disabled={!note.trim() || pending} className="rounded-md bg-gray-900 px-3 py-1.5 text-sm text-white disabled:opacity-40">log</button>
      </form>

      {data.comments.length > 0 && (
        <ul className="space-y-2">
          {thread.map((c, i) => (
            <li key={i} className="text-sm leading-snug text-gray-800">
              <span className="font-semibold">{c.who}:</span> <Linked text={c.text} />
              {c.when && <span className="ml-2 font-mono text-[11px] text-gray-400">{c.when}</span>}
            </li>
          ))}
          {data.comments.length > 3 && (
            <li>
              <button type="button" onClick={() => setAll((v) => !v)} className="text-xs text-gray-500 hover:underline">
                {all ? 'fewer' : `${data.comments.length - 3} more`}
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
