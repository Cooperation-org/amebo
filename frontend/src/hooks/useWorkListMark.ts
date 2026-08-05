import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiClient, type WorkItem, type WorkList, type WorkMarkState } from '@/src/lib/api';

/**
 * Pin a row, bury it, or take the mark off again.
 *
 * A pin is an override, not a score: the server lifts pinned rows out before it
 * applies the cap, so the client never re-sorts them by rank. Burying is the
 * same gesture pointing down, and it is neither a delete nor forever.
 *
 * Nothing here confirms first. The standard pattern for a reversible action is
 * to do it at once and offer the way back (ui-patterns.com/patterns/undo,
 * GitLab Pajamas destructive-actions): a dialog in front of something this cheap
 * costs a press every time to save a press almost never. So the press lands
 * immediately, the row moves before the server answers, and the undo rides along
 * on a toast. Unpin and unbury carry no toast — they are the undo.
 */

/** The order the server ranks in, so an optimistic row lands where it will sit. */
const byRank = (a: WorkItem, b: WorkItem) =>
  b.rank - a.rank || a.title.localeCompare(b.title);

const without = (list: WorkItem[], subject: string) =>
  list.filter((i) => i.subject !== subject);

const find = (list: WorkList, subject: string) =>
  [...list.pinned, ...list.live, ...list.past, ...list.buried]
    .find((i) => i.subject === subject);

/** Move a row into its new bucket without waiting for the round trip. */
function moved(list: WorkList, subject: string, state: WorkMarkState | null): WorkList {
  const item = find(list, subject);
  if (!item) return list;

  const rest: WorkList = {
    ...list,
    pinned: without(list.pinned, subject),
    live: without(list.live, subject),
    past: without(list.past, subject),
    buried: without(list.buried, subject),
  };

  // Newest pin last: the server keeps them in the order they were pinned.
  if (state === 'pinned') return { ...rest, pinned: [...rest.pinned, item] };
  if (state === 'buried') return { ...rest, buried: [...rest.buried, item] };

  // Unmarked: back where its own rank puts it. A row that went past its date
  // belongs in `past`, which is where it came from.
  const back = [...(item.past ? rest.past : rest.live), item].sort(byRank);
  return item.past ? { ...rest, past: back } : { ...rest, live: back };
}

export type MarkVars = { subject: string; state: WorkMarkState | null };

export function useMarkWorkItem() {
  const qc = useQueryClient();

  const apply = ({ subject, state }: MarkVars) =>
    state ? apiClient.markWorkItem(subject, state) : apiClient.clearWorkMark(subject);

  return useMutation({
    mutationFn: apply,

    onMutate: async ({ subject, state }: MarkVars) => {
      await qc.cancelQueries({ queryKey: ['work-list'] });
      const previous = qc.getQueryData<WorkList>(['work-list']);
      if (previous) qc.setQueryData<WorkList>(['work-list'], moved(previous, subject, state));
      return { previous };
    },

    onError: (_err, _vars, context) => {
      // Put back exactly what was there. Nothing the person did is lost.
      if (context?.previous) qc.setQueryData(['work-list'], context.previous);
      toast.error("That didn't save.");
    },

    onSuccess: (_data, { subject, state }: MarkVars) => {
      if (!state) return;
      const undo = () => {
        // The mark is already written, so undo is its own small write rather
        // than a rollback: clear it and let the list refetch.
        apiClient.clearWorkMark(subject)
          .then(() => qc.invalidateQueries({ queryKey: ['work-list'] }))
          .catch(() => toast.error("That didn't come back."));
        // Move it back on screen at once, same as the press that put it there.
        const now = qc.getQueryData<WorkList>(['work-list']);
        if (now) qc.setQueryData<WorkList>(['work-list'], moved(now, subject, null));
      };
      toast(state === 'pinned' ? 'Pinned to the top.' : 'Pushed down, on the buried list.',
            { action: { label: 'Undo', onClick: undo } });
    },

    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['work-list'] });
    },
  });
}
