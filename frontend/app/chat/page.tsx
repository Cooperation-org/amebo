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
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/src/store/useAuthStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { User, LogOut, LayoutDashboard } from 'lucide-react';

// Default instance comes from env; a ?instance=<slug> query param overrides it.
// Empty string means "no instance" -> backend uses its web-default.
const DEFAULT_INSTANCE = process.env.NEXT_PUBLIC_DEFAULT_INSTANCE || '';

export default function ChatPage() {
  const [instance, setInstance] = useState<string>(DEFAULT_INSTANCE);
  const [instanceName, setInstanceName] = useState<string>('Amebo');
  const [input, setInput] = useState('');
  const [speakReplies, setSpeakReplies] = useState(false);
  const [resumeSession, setResumeSession] = useState<string | undefined>(undefined);

  const { turns, send, sending, error, reset } = useChat(instance, resumeSession);
  const bottomRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { user, logout } = useAuthStore();

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  // Read ?instance= once on mount (avoids useSearchParams' Suspense requirement).
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const q = params.get('instance');
    if (q) setInstance(q);
    // ?session=<id> resumes a conversation picked from the dashboard chat list.
    const s = params.get('session');
    if (s) setResumeSession(s);
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
    <div className="flex h-[100dvh] flex-col bg-background text-foreground">
      {/* Header */}
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h1 className="truncate text-base font-semibold">{instanceName}</h1>
          <p className="truncate text-xs text-muted-foreground">
            Talking to amebo{instance ? ` · ${instance}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
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
              {speakReplies ? '🔊 Voice on' : '🔈 Voice off'}
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
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="rounded-full" title={user?.email || 'Account'}>
                <User className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {user?.email && (
                <div className="max-w-[220px] truncate px-2 py-1.5 text-xs text-muted-foreground">
                  {user.email}
                </div>
              )}
              <DropdownMenuItem asChild>
                <a href="/dashboard" className="flex items-center">
                  <LayoutDashboard className="mr-2 h-4 w-4" />
                  Dashboard
                </a>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={handleLogout} className="flex items-center">
                <LogOut className="mr-2 h-4 w-4" />
                Logout
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      {/* Messages */}
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
  );
}
