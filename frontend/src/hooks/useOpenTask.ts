'use client';

import { useCallback } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';

/**
 * Which task is open, kept in the address bar.
 *
 * Golda: "when a task is popped up it should have url route so i could share
 * it" — and later, "how i even share it". An open task held only in component
 * state cannot be copied, sent to anyone, bookmarked, or reloaded.
 *
 * A search param rather than a nested route: the list stays mounted underneath,
 * so opening and closing costs no fetch and no flash of an empty page. Back
 * closes the task instead of leaving the list, which is what the browser's own
 * back button means to a person looking at an overlay.
 *
 * `?task=<subject>` — the subject is the item's own identifier ('taiga:slug#4',
 * 'goal:<uuid>', 'draft:<uuid>'), so the link names the thing itself and keeps
 * working however the row got onto the list.
 */
export function useOpenTask() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const open = params.get('task');

  const setOpen = useCallback(
    (subject: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (subject) next.set('task', subject);
      else next.delete('task');
      const query = next.toString();
      // push when opening so back closes it; replace when closing so a closed
      // task does not pile up a history entry of its own.
      const url = query ? `${pathname}?${query}` : pathname;
      if (subject) router.push(url, { scroll: false });
      else router.replace(url, { scroll: false });
    },
    [params, pathname, router],
  );

  return { open, setOpen };
}
