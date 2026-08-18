/**
 * Where a board link is allowed to go.
 *
 * Marten, never Taiga's own interface — Golda: "NO links that way only marten
 * interface svelte good, taiga interface NO".
 *
 * The backend already builds Marten URLs for every row it assembles
 * (`work_list.story_url`). This is for URLs that arrive from somewhere else —
 * a Taiga link somebody typed into a MAIN.md by hand — so one of those cannot
 * put a person back on the old interface.
 *
 * A Taiga URL that cannot be mapped returns undefined. No link is better than a
 * link to the interface we do not use.
 */
const MARTEN = process.env.NEXT_PUBLIC_MARTEN_URL || 'https://marten.linkedtrust.us';

/** https://taiga.<host>/project/<slug>/us/<ref> — a single story. */
const STORY = /^https?:\/\/taiga\.[^/]+\/project\/([^/?#]+)\/us\/(\d+)/i;
/** https://taiga.<host>/project/<slug>/... — anything else on a known board. */
const PROJECT = /^https?:\/\/taiga\.[^/]+\/project\/([^/?#]+)/i;
const TAIGA = /^https?:\/\/taiga\.[^/]+/i;

export function boardLink(url: string | null | undefined): string | undefined {
  const raw = (url || '').trim();
  if (!raw) return undefined;

  const story = raw.match(STORY);
  if (story) return `${MARTEN}/p/${story[1]}/board?story=${story[2]}`;

  const project = raw.match(PROJECT);
  if (project) return `${MARTEN}/p/${project[1]}/board`;

  // A Taiga URL with no board in it names nothing we can open in Marten.
  if (TAIGA.test(raw)) return undefined;

  return raw;
}
