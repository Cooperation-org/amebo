'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { useChat } from '@/src/hooks/useChat';
import {
  useSpeechInput,
  speak,
  stopSpeaking,
  speechSynthesisSupported,
} from '@/src/hooks/useVoice';
import { apiClient } from '@/src/lib/api';
import { useChatThreads } from '@/src/hooks/useChatThreads';
import { useQuery } from '@tanstack/react-query';
import { Menu, Plus } from 'lucide-react';
import { AmeboNav } from '@/src/components/AmeboNav';

// Default instance comes from env; a ?instance=<slug> query param overrides it.
// Empty string means "no instance" -> backend uses its web-default.
const DEFAULT_INSTANCE = process.env.NEXT_PUBLIC_DEFAULT_INSTANCE || '';

export default function ChatPage() {
  const [instance, setInstance] = useState<string>(DEFAULT_INSTANCE);
  const [instanceName, setInstanceName] = useState<string>('Amebo');
  const [input, setInput] = useState('');
  const [speakReplies, setSpeakReplies] = useState(false);
  const [resumeSession, setResumeSession] = useState<string | undefined>(undefined);
  const [listOpen, setListOpen] = useState(false);
  const { data: threads } = useChatThreads();
  // What amebo can be asked to do, in the skill's own words. The API leaves out
  // any skill with no button, and an org's own skills shadow the core ones, so
  // this list is per-org without this page knowing anything about skills.
  const { data: skills } = useQuery({
    queryKey: ['skills', 'founder'],
    queryFn: () => apiClient.getSkills('founder'),
    staleTime: 5 * 60 * 1000,
  });

  const { turns, send, sending, error, reset } = useChat(instance, resumeSession);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Read ?instance= once on mount (avoids useSearchParams' Suspense requirement).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const q = params.get('instance');
    if (q) setInstance(q);
    // ?session=<id> resumes a conversation picked from the dashboard chat list.
    const s = params.get('session');
    if (s) setResumeSession(s);
    // ?ask=<text> arrives from a button somewhere else (the cohort dash skill
    // buttons). It fills the box and waits: the person sends it, so they can
    // add what they know before amebo starts.
    const a = params.get('ask');
    if (a) setInput(a);
    // Voice replies are OFF by default every load — amebo listens and outputs
    // text; it does not speak unless the user explicitly toggles it on.
  }, []);

  // Resolve the instance's display name for the header.
  useEffect(() => {
    let cancelled = false;
    if (!instance) {
      setInstanceName('Amebo');
      return;
    }
    apiClient
      .getInstanceInfo(instance)
      .then((info) => {
        if (!cancelled) setInstanceName(info.name || instance);
      })
      .catch(() => {
        if (!cancelled) setInstanceName(instance);
      });
    return () => {
      cancelled = true;
    };
  }, [instance]);

  // Auto-scroll to the latest turn.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns]);

  const doSend = useCallback(
    async (text: string) => {
      const reply = await send(text);
      if (reply && speakReplies) speak(reply);
    },
    [send, speakReplies]
  );

  const onSpeech = useCallback(
    (transcript: string) => {
      setInput('');
      void doSend(transcript);
    },
    [doSend]
  );

  const { supported: micSupported, listening, toggle: toggleMic } =
    useSpeechInput(onSpeech);

  const handleSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const text = input.trim();
      if (!text || sending) return;
      setInput('');
      void doSend(text);
    },
    [input, sending, doSend]
  );

  const toggleSpeak = useCallback(() => {
    setSpeakReplies((prev) => {
      const next = !prev;
      if (typeof window !== 'undefined') {
        localStorage.setItem('amebo-chat-speak', next ? '1' : '0');
      }
      if (!next) stopSpeaking();
      return next;
    });
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background text-foreground">
      {/* The one Amebo bar, same as every other Amebo page. Chat's own
          controls ride in its right slot instead of a second row. */}
      <AmeboNav
        right={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setListOpen((v) => !v)}
              aria-label="Conversations"
              className="shrink-0 rounded-md p-1.5 text-gray-600 hover:bg-gray-100"
            >
              <Menu className="h-4 w-4" />
            </button>
            {speechSynthesisSupported() && (
              <button
                type="button"
                onClick={toggleSpeak}
                aria-pressed={speakReplies}
                className={`rounded-md px-2 py-1 text-xs font-medium transition ${
                  speakReplies
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-muted-foreground hover:bg-muted/80'
                }`}
                title={speakReplies ? 'Voice replies on' : 'Voice replies off'}
              >
                {speakReplies ? '\u{1F50A} Voice on' : '\u{1F508} Voice off'}
              </button>
            )}
            <button
              type="button"
              onClick={reset}
              className="rounded-md bg-muted px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-muted/80"
              title="Start a new conversation"
            >
              New
            </button>
          </div>
        }
      />

      {/* Everything below the bar. Position the conversations pop-out against
          this box, so it never has to guess how tall the bars above are. */}
      <div className="relative flex min-h-0 flex-1 flex-col">
      {/* Conversations pop-out: overlays from the left, never occupies layout */}
      {listOpen && (
        <div className="absolute inset-0 z-30">
          <div
            className="absolute inset-0 bg-black/20"
            onClick={() => setListOpen(false)}
          />
          <div className="absolute bottom-0 left-0 top-0 w-72 overflow-y-auto border-r border-border bg-background p-2 shadow-lg">
            <button
              type="button"
              onClick={() => { setListOpen(false); window.location.href = '/chat'; }}
              className="mb-1 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-muted"
            >
              <Plus className="h-4 w-4" /> New chat
            </button>
            {(threads ?? []).map((t) => (
              <button
                key={t.session_id}
                type="button"
                onClick={() => {
                  setListOpen(false);
                  window.location.href = `/chat?session=${encodeURIComponent(t.session_id)}`;
                }}
                className="block w-full rounded-md px-3 py-2 text-left hover:bg-muted"
              >
                <p className="line-clamp-2 text-sm text-foreground">{t.title || t.snippet || 'Conversation'}</p>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Messages, with the skills rail beside them on a wide screen */}
      <div className="flex min-h-0 flex-1">
      <main className="flex-1 overflow-y-auto px-4 py-4">
        <div className="mx-auto flex max-w-2xl flex-col gap-4">
          {turns.length === 0 && (
            <div className="mt-12 text-center text-sm text-muted-foreground">
              <p className="text-2xl">👋</p>
              <p className="mt-2">
                Ask {instanceName} anything about your team&apos;s work.
              </p>
            </div>
          )}

          {turns.map((turn, i) => (
            <div
              key={i}
              className={turn.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm ${
                  turn.role === 'user'
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-muted text-foreground'
                }`}
              >
                {turn.role === 'assistant' && turn.pending ? (
                  <span className="inline-flex gap-1">
                    <span className="animate-pulse">•</span>
                    <span className="animate-pulse [animation-delay:150ms]">•</span>
                    <span className="animate-pulse [animation-delay:300ms]">•</span>
                  </span>
                ) : turn.role === 'assistant' ? (
                  <div className="prose prose-sm dark:prose-invert max-w-none break-words">
                    <ReactMarkdown>{turn.text}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap break-words">{turn.text}</p>
                )}
              </div>
            </div>
          ))}

          {error && (
            <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      {(skills ?? []).length > 0 && (
        <aside className="hidden w-64 shrink-0 overflow-y-auto border-l border-border p-3 lg:block">
          <p className="px-1 pb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Ask amebo
          </p>
          {(skills ?? []).map((s) => (
            <button
              key={s.name}
              type="button"
              title={s.description}
              onClick={() => setInput(s.ask)}
              className="mb-1 block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-muted"
            >
              {s.button}
            </button>
          ))}
          <p className="px-1 pt-2 text-xs text-muted-foreground">
            Puts the question in the box. Change it before you send it.
          </p>
        </aside>
      )}
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="border-t border-border px-4 py-3"
      >
        <div className="mx-auto flex max-w-2xl items-end gap-2">
          {micSupported && (
            <button
              type="button"
              onClick={toggleMic}
              aria-pressed={listening}
              className={`shrink-0 rounded-full p-2.5 text-lg transition ${
                listening
                  ? 'bg-destructive text-destructive-foreground animate-pulse'
                  : 'bg-muted text-muted-foreground hover:bg-muted/80'
              }`}
              title={listening ? 'Listening… tap to stop' : 'Speak'}
            >
              🎤
            </button>
          )}
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                handleSubmit(e);
              }
            }}
            rows={1}
            placeholder={`Message ${instanceName}…`}
            className="max-h-40 flex-1 resize-none rounded-2xl border border-border bg-background px-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-primary"
          />
          <button
            type="submit"
            disabled={sending || !input.trim()}
            className="shrink-0 rounded-full bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {sending ? '…' : 'Send'}
          </button>
        </div>
      </form>
      </div>
    </div>
  );
}
