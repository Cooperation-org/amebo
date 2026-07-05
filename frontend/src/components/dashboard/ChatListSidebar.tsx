'use client';

import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Plus, MessageSquare } from 'lucide-react';
import { useChatThreads, type ChatThreadSummary } from '@/src/hooks/useChatThreads';

function timeAgo(iso: string | null): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (isNaN(then)) return '';
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function ThreadRow({ t }: { t: ChatThreadSummary }) {
  const label = t.title || t.snippet || 'Conversation';
  return (
    <Link
      href={`/chat?session=${encodeURIComponent(t.session_id)}`}
      className="block rounded-md px-3 py-2 hover:bg-gray-100 transition-colors"
    >
      <p className="text-sm text-gray-800 line-clamp-2">{label}</p>
      {t.updated_at && (
        <p className="text-[11px] text-gray-400 mt-0.5">{timeAgo(t.updated_at)}</p>
      )}
    </Link>
  );
}

/**
 * The user's own recent conversations with amebo. Read-only list; clicking one
 * opens it in the chat interface (resumes it), New Chat starts a fresh one.
 * Renders real content only (a New Chat button is a real action, never a blank
 * placeholder).
 */
export function ChatListSidebar() {
  const { data: threads, isLoading } = useChatThreads();

  return (
    <aside className="order-last lg:order-first lg:w-64 lg:flex-shrink-0">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
          Conversations
        </h2>
        <Button asChild size="sm" variant="ghost" className="h-7 text-gray-600">
          <Link href="/chat">
            <Plus className="h-3.5 w-3.5 mr-1" />
            New
          </Link>
        </Button>
      </div>

      {!isLoading && (threads?.length ?? 0) === 0 ? (
        <Button asChild variant="outline" className="w-full justify-start">
          <Link href="/chat">
            <MessageSquare className="h-4 w-4 mr-2" />
            Start a conversation
          </Link>
        </Button>
      ) : (
        <div className="space-y-0.5">
          {(threads ?? []).map((t) => (
            <ThreadRow key={t.session_id} t={t} />
          ))}
        </div>
      )}
    </aside>
  );
}
