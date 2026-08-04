import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient, type WorkEdit, type WorkItem, type WorkItemDetail, type WorkList } from '@/src/lib/api';

export type { WorkItemDetail };

/** The whole record behind a row, plus what people said on it. */
export function useWorkItem(subject: string | null) {
  return useQuery<WorkItemDetail>({
    queryKey: ['work-item', subject],
    queryFn: () => apiClient.getWorkItem(subject as string),
    enabled: !!subject,
    staleTime: 15 * 1000,
    // A refetch while the sheet is open used to overwrite unsaved words. The
    // fields also guard themselves, but not re-fetching under someone's hands
    // is the simpler half of the fix.
    refetchOnWindowFocus: false,
  });
}

/**
 * A sheet opened from a claw row is keyed by the row's subject, but its edits
 * carry the shown task's subject. Both are needed to take the right row off the
 * list the moment someone archives it, so the caller may name the row it came
 * from. `rowSubject` never reaches the server.
 */
export type WorkEditVars = WorkEdit & { rowSubject?: string };

/** Archiving, deleting or closing takes an item off the list outright. */
const removesFromList = (body: WorkEditVars) =>
  Boolean(body.archive || body.delete || body.close);

/**
 * Applies the change straight away. No draft, no approval step: the gate exists
 * to stop the claw acting alone, and this is the human's own hand.
 *
 * The list also updates before the server answers. Archiving used to leave the
 * row sitting there through a round trip to Taiga and back, which reads as the
 * press not having worked. If the server refuses, the row comes back.
 */
export function useEditWorkItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: WorkEditVars) => {
      const body: WorkEditVars = { ...vars };
      delete body.rowSubject;
      return apiClient.editWorkItem(body);
    },

    onMutate: async (body: WorkEditVars) => {
      // Your words are on screen the moment you press Post. They do reach
      // Taiga, but Taiga's history feed lags a beat behind the write, so the
      // refetch that follows came back without them and the post read as
      // having failed. The server's copy replaces this one when it lands.
      if (body.comment) {
        await qc.cancelQueries({ queryKey: ['work-item'] });
        for (const key of [body.subject, body.rowSubject].filter(Boolean)) {
          qc.setQueryData<WorkItemDetail>(['work-item', key], (d) =>
            d ? { ...d, comments: [...d.comments, { who: 'you', text: body.comment as string }] } : d,
          );
        }
      }

      // Stop a refetch already in flight from landing on top of this.
      await qc.cancelQueries({ queryKey: ['work-list'] });
      const previous = qc.getQueryData<WorkList>(['work-list']);
      if (!previous) return { previous };

      const touched = new Set([body.subject, body.rowSubject].filter(Boolean));
      const isTouched = (item: WorkItem) => touched.has(item.subject);

      if (removesFromList(body)) {
        qc.setQueryData<WorkList>(['work-list'], {
          ...previous,
          live: previous.live.filter((i) => !isTouched(i)),
          past: previous.past.filter((i) => !isTouched(i)),
        });
      } else if (body.due_date) {
        // Snoozing shows its new date at once. Where the row then belongs in
        // the order is the server's call, and that answer arrives a moment
        // later, so do not guess at re-ranking here.
        const redate = (i: WorkItem) =>
          isTouched(i) ? { ...i, due: body.due_date as string } : i;
        qc.setQueryData<WorkList>(['work-list'], {
          ...previous,
          live: previous.live.map(redate),
          past: previous.past.map(redate),
        });
      }

      return { previous };
    },

    onError: (_err, _body, context) => {
      // Put back exactly what was there. Nothing the person did is lost.
      if (context?.previous) qc.setQueryData(['work-list'], context.previous);
    },

    onSettled: () => {
      // The whole prefix, not one subject: a sheet opened from a claw row is
      // keyed by the row's subject but edits carry the shown task's subject —
      // invalidating only the edited subject left the open sheet stale.
      qc.invalidateQueries({ queryKey: ['work-item'] });
      qc.invalidateQueries({ queryKey: ['work-list'] });
    },
  });
}
