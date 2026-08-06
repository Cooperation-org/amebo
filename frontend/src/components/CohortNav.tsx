'use client';

// The cohort's cross-app bar, the same one workers.vc, GovKit and Marten
// mount, so a person who reached Amebo from the dash can get back out of it.
// The script is served by the app that owns it (workers.vc); Amebo only says
// where to find it. Unset NEXT_PUBLIC_COHORT_NAV_SRC (the default) mounts
// nothing, which is what any non-cohort Amebo wants.
//
// No data-org: Amebo is per-cohort, not per-venture, so it has no org slug of
// its own to stamp. The bar asks GovKit who the person is and adopts their
// team when there is exactly one. No data-current either: the bar reads the
// hostname and path itself, which is what tells Amebo from the inbox.

import { createElement, useEffect } from 'react';

const SRC = process.env.NEXT_PUBLIC_COHORT_NAV_SRC;

export function CohortNav() {
  useEffect(() => {
    if (!SRC || document.querySelector('script[data-cohort-nav]')) return;
    const s = document.createElement('script');
    s.src = SRC;
    s.defer = true;
    s.dataset.cohortNav = '';
    document.head.appendChild(s);
  }, []);

  if (!SRC) return null;
  return createElement('cohort-nav');
}
