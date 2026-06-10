import { useState, useCallback, useRef, useEffect } from 'react';
import { apiClient, ChatMessageResponse } from '@/src/lib/api';

export interface ChatTurn {
  role: 'user' | 'assistant';
  text: string;
  confidence?: number;
  toolRounds?: number;
  pending?: boolean;
}

const sessionKey = (instance: string) => `amebo-chat-session:${instance}`;

/**
 * Conversational chat against amebo's agentic loop (POST /api/chat/message).
 * Keeps a server-side thread alive via session_id, persisted per instance so a
 * reload continues the same conversation. The transcript itself is client state
 * (the server owns the durable thread).
 */
export function useChat(instanceSlug: string) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef<string | undefined>(undefined);

  // Restore the per-instance session id when the instance changes.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    sessionId.current = localStorage.getItem(sessionKey(instanceSlug)) || undefined;
    setTurns([]);
    setError(null);
  }, [instanceSlug]);

  const send = useCallback(
    async (message: string): Promise<string | null> => {
      const text = message.trim();
      if (!text || sending) return null;
      setError(null);
      setTurns((t) => [
        ...t,
        { role: 'user', text },
        { role: 'assistant', text: '', pending: true },
      ]);
      setSending(true);
      try {
        const res: ChatMessageResponse = await apiClient.sendChatMessage({
          message: text,
          session_id: sessionId.current,
          instance_slug: instanceSlug,
        });
        sessionId.current = res.session_id;
        if (typeof window !== 'undefined') {
          localStorage.setItem(sessionKey(instanceSlug), res.session_id);
        }
        setTurns((t) => {
          const next = [...t];
          next[next.length - 1] = {
            role: 'assistant',
            text: res.reply,
            confidence: res.confidence,
            toolRounds: res.tool_rounds,
          };
          return next;
        });
        return res.reply;
      } catch (e) {
        // Drop the pending assistant turn, surface the error.
        setTurns((t) => t.slice(0, -1));
        setError(e instanceof Error ? e.message : 'Something went wrong');
        return null;
      } finally {
        setSending(false);
      }
    },
    [instanceSlug, sending]
  );

  const reset = useCallback(() => {
    sessionId.current = undefined;
    if (typeof window !== 'undefined') {
      localStorage.removeItem(sessionKey(instanceSlug));
    }
    setTurns([]);
    setError(null);
  }, [instanceSlug]);

  return { turns, send, sending, error, reset };
}
