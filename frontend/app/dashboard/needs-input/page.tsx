'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Send } from 'lucide-react';
import { useNeedsInput, useAnswerGoal, type Goal } from '@/src/hooks/useNeedsInput';

/**
 * Split a pin's description into the part to lead with (the questions) and
 * the background context. Pins created by the weekly fanout embed an
 * "Open questions:" section; goals without one just show their description.
 */
function splitDescription(description: string | null | undefined): {
  context: string;
  questions: string;
} {
  const text = (description || '').trim();
  const marker = 'Open questions:';
  const at = text.indexOf(marker);
  if (at === -1) return { context: text, questions: '' };
  const rest = text.slice(at + marker.length);
  const footerAt = rest.indexOf('\n\nFull context:');
  return {
    context: text.slice(0, at).trim(),
    questions: (footerAt === -1 ? rest : rest.slice(0, footerAt)).trim(),
  };
}

function displayTitle(goal: Goal): string {
  const short = goal.config?.short_name;
  if (short && goal.title.startsWith(short)) {
    return goal.title.slice(short.length).replace(/^\s*—\s*/, '');
  }
  return goal.title;
}

function Row({ goal }: { goal: Goal }) {
  const answer = useAnswerGoal();
  const [text, setText] = useState('');
  const [expanded, setExpanded] = useState(false);
  const { context, questions } = splitDescription(goal.description);
  const score = goal.config?.score;
  const short = goal.config?.short_name;

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    answer.mutate({ id: goal.id, answer: trimmed });
  };

  return (
    <div className="rounded-lg border bg-white px-4 py-3">
      <div className="flex items-baseline gap-2">
        {score != null && (
          <span className="text-sm font-semibold tabular-nums text-blue-700">
            {score}
          </span>
        )}
        <p className="min-w-0 flex-1 text-sm font-medium text-gray-900">
          {displayTitle(goal)}
        </p>
      </div>
      {short && <p className="mt-0.5 text-xs text-gray-400">{short}</p>}
      {questions && (
        <p className="mt-2 whitespace-pre-line text-sm text-gray-700">{questions}</p>
      )}
      {context && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="mt-1 text-xs font-medium text-blue-600 hover:underline"
        >
          {expanded ? 'Hide context' : 'Show context'}
        </button>
      )}
      {expanded && context && (
        <p className="mt-1 whitespace-pre-line text-sm text-gray-500">{context}</p>
      )}
      <div className="mt-2 flex items-end gap-2">
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Your answer — dictate or type"
          rows={2}
          className="min-h-[3rem] flex-1 text-base"
        />
        <Button
          size="sm"
          onClick={submit}
          disabled={answer.isPending || !text.trim()}
        >
          <Send className="mr-1 h-4 w-4" /> Send
        </Button>
      </div>
      {answer.isError && (
        <p className="mt-1 text-xs text-red-600">
          Couldn&apos;t save that answer — try again.
        </p>
      )}
    </div>
  );
}

/**
 * The needs-input queue: every goal waiting on a human, highest priority
 * (lowest score) first. Answering re-arms the goal and removes it from
 * the queue.
 */
export default function NeedsInputPage() {
  const { data: goals, isLoading } = useNeedsInput();
  if (isLoading) return null;
  if (!goals || goals.length === 0) {
    return <p className="text-sm text-gray-500">Nothing waiting on you.</p>;
  }
  return (
    <div className="mx-auto max-w-2xl space-y-2">
      <h1 className="text-base font-semibold text-gray-900">
        {goals.length} waiting on you
      </h1>
      {goals.map((g) => (
        <Row key={g.id} goal={g} />
      ))}
    </div>
  );
}
