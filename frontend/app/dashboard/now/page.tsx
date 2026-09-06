import { redirect } from 'next/navigation';

/** Now lived here for a day; the inbox is the right name (golda 2026-09-06). */
export default function NowPage() {
  redirect('/dashboard/list');
}
