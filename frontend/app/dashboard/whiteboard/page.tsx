import { redirect } from 'next/navigation';

/** The whiteboard was a chat under another name. Forwards to chat. */
export default function WhiteboardPage() {
  redirect('/chat');
}
