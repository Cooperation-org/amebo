import { redirect } from 'next/navigation';

/** One list. Needs-input forwards into it. */
export default function NeedsInputPage() {
  redirect('/dashboard/list');
}
