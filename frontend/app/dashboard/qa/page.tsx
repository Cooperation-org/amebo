import { redirect } from 'next/navigation';

/** Q&A was superseded by chat. Forwards there rather than 404ing. */
export default function QAPage() {
  redirect('/chat');
}
