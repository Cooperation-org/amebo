import { redirect } from 'next/navigation';

/**
 * There is one list. Approvals was a second place to look, so it forwards into
 * the list rather than 404ing — no dead end, no page that shows a subset of the
 * same work.
 */
export default function ApprovalsPage() {
  redirect('/dashboard/list');
}
