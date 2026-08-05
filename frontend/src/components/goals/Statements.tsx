'use client';

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  apiClient,
  type ResolvedStatement,
  type Statement,
  type StatementPatch,
} from '@/src/lib/api';

/**
 * What the org is aiming at — mission, vision, values, OKRs — above its goals.
 *
 * Golda 2026-08-05: "there should be a way for them to edit the things that
 * are affecting their prioritization ... it has to be simple and not messy,
 * but also flexible and be able to take input from different sources."
 *
 * So: the name of the relation is a free-text box, not a dropdown, and the
 * words are either pasted here or pointed at. Everything on screen is the field
 * itself (UX_PRINCIPLES §4), saving on blur (§6), with no sentence anywhere
 * explaining the model (§5). Words a pointer leads to are shown under it rather
 * than described (§1).
 *
 * Inline editing follows the NN/g pattern (nngroup.com "Inline Editing"):
 * the value is the control, edits commit on blur, and the row never enters a
 * separate mode. Checkbox and dialog semantics follow the WAI-ARIA APG.
 */

/** Edits in place and commits on blur. Server values never clobber unsaved
 *  words — the same rule the task sheet uses. */
function Field({
  value,
  onSave,
  placeholder,
  multiline,
  className = '',
}: {
  value: string;
  onSave: (next: string) => void;
  placeholder?: string;
  multiline?: boolean;
  className?: string;
}) {
  const [draft, setDraft] = useState(value);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) setDraft(value);
  }, [value, dirty]);
  useEffect(() => {
    if (dirty && value === draft) setDirty(false);
  }, [value, draft, dirty]);

  const commit = () => {
    if (draft !== value) onSave(draft);
  };

  const shared =
    'w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-gray-900 hover:border-gray-200 focus:border-emerald-600 focus:bg-white focus:outline-none';

  return multiline ? (
    <textarea
      value={draft}
      placeholder={placeholder}
      rows={Math.min(10, Math.max(2, draft.split('\n').length))}
      onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
      onBlur={commit}
      className={`${shared} resize-y leading-relaxed ${className}`}
    />
  ) : (
    <input
      value={draft}
      placeholder={placeholder}
      onChange={(e) => { setDraft(e.target.value); setDirty(true); }}
      onBlur={commit}
      className={`${shared} ${className}`}
    />
  );
}

function Row({
  statement,
  resolved,
  onPatch,
  onDelete,
}: {
  statement: Statement;
  resolved?: ResolvedStatement;
  onPatch: (patch: StatementPatch) => void;
  onDelete: () => void;
}) {
  const proposed = statement.accepted_at === null;
  const pointing = statement.pointer !== null;
  const isUrl = /^https?:\/\//i.test(statement.pointer ?? '');

  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        proposed ? 'border-amber-300 bg-amber-50' : 'border-gray-200 bg-white'
      }`}
    >
      <div className="flex items-center gap-2">
        <Field
          value={statement.name}
          onSave={(name) => onPatch({ name })}
          placeholder="mission"
          className="flex-1 text-[13px] font-bold uppercase tracking-widest text-gray-500"
        />
        <label className="flex shrink-0 cursor-pointer items-center gap-1.5 px-1 text-xs text-gray-500">
          <input
            type="checkbox"
            checked={statement.informs_priority}
            onChange={(e) => onPatch({ informs_priority: e.target.checked })}
            className="h-3.5 w-3.5 accent-emerald-600"
          />
          weighs in
        </label>
        <button
          type="button"
          onClick={onDelete}
          aria-label={`Remove ${statement.name}`}
          className="shrink-0 rounded px-2 py-1 text-sm text-gray-300 hover:bg-gray-100 hover:text-gray-700"
        >
          ×
        </button>
      </div>

      {pointing ? (
        <>
          <Field
            value={statement.pointer ?? ''}
            onSave={(pointer) => onPatch({ pointer })}
            className="font-mono text-[13px] text-gray-700"
          />
          {isUrl && (
            <a
              href={statement.pointer ?? '#'}
              target="_blank"
              rel="noreferrer"
              className="ml-2 text-xs text-emerald-700 hover:underline"
            >
              open ↗
            </a>
          )}
          {resolved ? (
            <p className="mt-1 whitespace-pre-wrap px-2 text-[13px] leading-relaxed text-gray-500">
              {resolved.text.slice(0, 600)}
            </p>
          ) : (
            statement.informs_priority && (
              <p className="mt-1 px-2 text-xs text-amber-700">nothing read from here</p>
            )
          )}
        </>
      ) : (
        <Field
          value={statement.body ?? ''}
          onSave={(body) => onPatch({ body })}
          multiline
          className="text-[15px]"
        />
      )}

      <div className="mt-1 flex items-center gap-2 px-2">
        <Field
          value={statement.source}
          onSave={(source) => onPatch({ source })}
          placeholder="where this came from"
          className="flex-1 text-xs text-gray-400"
        />
        {proposed && (
          <button
            type="button"
            onClick={() => onPatch({ accept: true })}
            className="shrink-0 rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-emerald-700"
          >
            Keep
          </button>
        )}
      </div>
    </div>
  );
}

/** Paste anything, name it, save. The whole import path for now — a photographed
 *  whiteboard is typed in here by a person. */
function Add({ onAdd }: { onAdd: (name: string, text: string) => void }) {
  const [name, setName] = useState('');
  const [text, setText] = useState('');

  const pointerish = /^(https?:\/\/|repo:|abra:)/i.test(text.trim());
  const ready = name.trim().length > 0 && text.trim().length > 0;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready) return;
        onAdd(name.trim(), text.trim());
        setName('');
        setText('');
      }}
      className="rounded-lg border border-dashed border-gray-300 px-3 py-2"
    >
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="mission"
        aria-label="What this is"
        className="w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-[13px] font-bold uppercase tracking-widest text-gray-500 placeholder:normal-case placeholder:tracking-normal placeholder:text-gray-300 hover:border-gray-200 focus:border-emerald-600 focus:bg-white focus:outline-none"
      />
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        placeholder="their words, or a link to them"
        aria-label="The words, or a pointer to them"
        className={`w-full rounded-md border border-transparent bg-transparent px-2 py-1 leading-relaxed text-gray-900 placeholder:text-gray-300 hover:border-gray-200 focus:border-emerald-600 focus:bg-white focus:outline-none ${
          pointerish ? 'font-mono text-[13px]' : 'text-[15px]'
        }`}
      />
      {ready && (
        <button
          type="submit"
          className="mt-1 rounded-md bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-700"
        >
          Add
        </button>
      )}
    </form>
  );
}

export function Statements() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery<Statement[]>({
    queryKey: ['statements'],
    queryFn: () => apiClient.getStatements(),
    staleTime: 30 * 1000,
  });
  // The words behind the pointers, so a link is never shown on its own.
  const { data: resolved } = useQuery<ResolvedStatement[]>({
    queryKey: ['statements', 'resolved'],
    queryFn: () => apiClient.getResolvedStatements(),
    staleTime: 30 * 1000,
  });

  const refresh = () => { void qc.invalidateQueries({ queryKey: ['statements'] }); };

  const add = useMutation({
    mutationFn: ({ name, text }: { name: string; text: string }) =>
      apiClient.addStatement(
        /^(https?:\/\/|repo:|abra:)/i.test(text)
          ? { name, pointer: text, informs_priority: true }
          : { name, body: text, informs_priority: true },
      ),
    onSuccess: refresh,
  });
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: StatementPatch }) =>
      apiClient.editStatement(id, body),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiClient.deleteStatement(id),
    onSuccess: refresh,
  });

  if (isLoading) return null;
  const rows = data ?? [];
  const byId = new Map((resolved ?? []).map((r) => [r.id, r]));

  return (
    <section className="space-y-2">
      <h2 className="text-[11px] font-bold uppercase tracking-widest text-gray-400">
        Aiming at
      </h2>
      {rows.map((s) => (
        <Row
          key={s.id}
          statement={s}
          resolved={byId.get(s.id)}
          onPatch={(body) => patch.mutate({ id: s.id, body })}
          onDelete={() => remove.mutate(s.id)}
        />
      ))}
      <Add onAdd={(name, text) => add.mutate({ name, text })} />
    </section>
  );
}
