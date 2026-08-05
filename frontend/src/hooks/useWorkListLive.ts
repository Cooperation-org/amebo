'use client';

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { API_BASE_URL } from '@/src/lib/api';

/**
 * Refetch the list the moment amebo changes it.
 *
 * The stream carries no content, only "look again" — the list is still fetched
 * through the one endpoint that assembles it, so there is never a second copy
 * of the truth arriving by a different road.
 *
 * EventSource, not a socket: this is one direction, it is plain HTTP so the
 * session cookie comes along by itself, and the browser reconnects on its own
 * when a laptop wakes or a connection drops. Nothing here has to manage that.
 */
export function useWorkListLive() {
  const qc = useQueryClient();

  useEffect(() => {
    // withCredentials sends the session cookie, which is the only auth this
    // needs — EventSource cannot set a header, so a bearer token is not an
    // option and does not have to be one.
    const url = `${API_BASE_URL}/api/work-list/stream`;
    let source: EventSource;
    try {
      source = new EventSource(url, { withCredentials: true });
    } catch {
      return;   // no stream available: the fallback refresh still covers it
    }

    const look = () => qc.invalidateQueries({ queryKey: ['work-list'] });
    source.addEventListener('changed', look);

    return () => {
      source.removeEventListener('changed', look);
      source.close();
    };
  }, [qc]);
}
