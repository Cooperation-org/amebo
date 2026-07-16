'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Check } from 'lucide-react';
import { useWhiteboard, useAddWhiteboardEntry, type WhiteboardEntry } from '@/src/hooks/useWhiteboard';

function when(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

function Entry({ entry }: { entry: WhiteboardEntry }) {
  return (
    <div className="rounded-lg border bg-white px-4 py-2.5">
      <p className="whitespace-pre-wrap text-sm text-gray-900">{entry.text}</p>
      <p className="mt-1 text-xs text-gray-400">
        {entry.author} · {when(entry.created_at)}
        {entry.processed_at && (
          <span className="ml-2 inline-flex items-center text-green-600">
            <Check className="mr-0.5 h-3 w-3" /> filed
          </span>
        )}
      </p>
    </div>
  );
}

/**
 * The whiteboard: an INPUT surface, like a chatter log — not a record of
 * anything. Jot project talk as it happens ("got paid 800 on streetwell",
 * "deadline moved to friday"); amebo reads the unfiled entries, puts each fact
 * where it belongs (projects tracker, knowledge base, tasks, CRM) and marks
 * the entry filed. Write here; look for the facts in their real homes.
 */
export default function WhiteboardPage() {
  const { data: entries, isLoading } = useWhiteboard();
  const add = useAddWhiteboardEntry();
  const [text, setText] = useState('');

  const submit = () => {
    const t = text.trim();
    if (!t) return;
    add.mutate(t, { onSuccess: () => setText('') });
  };

  return (
    <div className="space-y-3">
      <h1 className="sr-only">Whiteboard</h1>
      <div className="flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Jot it down — amebo files the facts where they belong."
          className="min-h-[60px] flex-1 text-sm"
          maxLength={4000}
        />
        <Button disabled={add.isPending || !text.trim()} onClick={submit}>
          Add
        </Button>
      </div>
      {isLoading ? null : !entries || entries.length === 0 ? (
        <p className="text-sm text-gray-500">Nothing on the board.</p>
      ) : (
        <div className="space-y-2">
          {entries.map((e) => (
            <Entry key={e.id} entry={e} />
          ))}
        </div>
      )}
    </div>
  );
}
