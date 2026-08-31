'use client';

// The cohort's cross-app bar, the same one workers.vc, GovKit, Marten and elm
// mount, so a person who reached Amebo from the dash can get back out of it.
// The script is served by the app that owns it (workers.vc); Amebo only says
// where to find it.
//
// NEXT_PUBLIC_COHORT_NAV_SRC pins that address. Unset, it is derived from the
// page's own registrable domain — amebo.workers.vc asks workers.vc — and the
// element is dropped if the script fails to load, so a non-cohort Amebo shows
// nothing.
//
// No data-org: Amebo is per-cohort, not per-venture, so it has no org slug of
// its own to stamp. The bar asks GovKit who the person is and adopts their
// team when there is exactly one. No data-current either: the bar reads the
// hostname and path itself, which is what tells Amebo from the inbox.

import { createElement, useEffect, useState } from 'react';

const PINNED = process.env.NEXT_PUBLIC_COHORT_NAV_SRC;

export function CohortNav() {
  const [shown, setShown] = useState(true);

  useEffect(() => {
    if (document.querySelector('script[data-cohort-nav]')) return;
    const host = location.hostname.split('.').slice(-2).join('.');
    const src = PINNED || (host ? `https://${host}/static/embed/cohort-nav.js` : '');
    if (!src) {
      setShown(false);
      return;
    }
    const s = document.createElement('script');
    s.src = src;
    s.defer = true;
    s.dataset.cohortNav = '';
    s.onerror = () => setShown(false);
    document.head.appendChild(s);
  }, []);

  if (!shown) return null;
  return createElement('cohort-nav');
}
