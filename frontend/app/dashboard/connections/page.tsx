'use client';

/**
 * Connections — per-org OAuth credential management.
 *
 * Org admins land here to connect, see, and revoke external accounts
 * (Gmail, Slack, GitHub, etc.) on behalf of their org. The page is
 * intentionally small: a list of known providers, status per provider,
 * and one button per row.
 *
 * It calls `/api/connections/*` with the user's JWT. Service-to-service
 * callers (the dispatcher) use the same endpoints with X-API-Key.
 */

import { useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Plug, Link2, Trash2, ShieldCheck, AlertTriangle, Clock } from 'lucide-react';
import { toast } from 'sonner';
import { apiClient, type ConnectionSummary } from '@/src/lib/api';

/**
 * Provider catalog — the kinds we know how to talk to. Keeping this in
 * the frontend avoids a chatty "what kinds do you support?" round-trip
 * and lets us render descriptions + scopes consistently. New providers
 * land here in lockstep with their adapter in the backend.
 */
type ProviderDef = {
  kind: string;
  displayName: string;
  description: string;
  defaultScopes: string[];
};

const PROVIDERS: ProviderDef[] = [
  {
    kind: 'google',
    displayName: 'Google',
    description: 'Gmail, Calendar, and Drive on behalf of your org.',
    defaultScopes: [
      'https://www.googleapis.com/auth/gmail.send',
      'https://www.googleapis.com/auth/gmail.readonly',
      'https://www.googleapis.com/auth/calendar.readonly',
    ],
  },
  // Add more providers here as backend adapters land.
];

/* ------------------------------------------------------------------------- */

type Row = {
  provider: ProviderDef;
  connection: ConnectionSummary | null;
};

function buildRows(connections: ConnectionSummary[]): Row[] {
  const byKind = new Map<string, ConnectionSummary>();
  for (const c of connections) {
    // Prefer the default-label, active row.
    if (c.revoked_at) continue;
    if (!byKind.has(c.kind) || c.label === 'default') {
      byKind.set(c.kind, c);
    }
  }
  return PROVIDERS.map((p) => ({
    provider: p,
    connection: byKind.get(p.kind) ?? null,
  }));
}

function fmt(d: string | null | undefined): string {
  if (!d) return '—';
  try {
    return new Date(d).toLocaleString();
  } catch {
    return d;
  }
}

/* ------------------------------------------------------------------------- */

export default function ConnectionsPage() {
  const [connections, setConnections] = useState<ConnectionSummary[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await apiClient.listConnections();
      setConnections(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load connections';
      toast.error(msg);
      setConnections([]);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const rows = useMemo(
    () => (connections ? buildRows(connections) : []),
    [connections],
  );

  async function handleConnect(provider: ProviderDef) {
    setBusy(provider.kind);
    try {
      const result = await apiClient.startConnection(provider.kind, {
        scopes: provider.defaultScopes,
      });
      // Open the connect URL in a new tab so the user keeps this page.
      window.open(result.connect_url, '_blank', 'noopener,noreferrer');
      toast.success(`Opened ${provider.displayName} authorization in a new tab.`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to start connection';
      toast.error(msg);
    } finally {
      setBusy(null);
    }
  }

  async function handleRevoke(provider: ProviderDef, conn: ConnectionSummary) {
    if (!confirm(`Disconnect ${provider.displayName}? Anything pursuing this credential will need it reconnected.`)) {
      return;
    }
    setBusy(provider.kind);
    try {
      await apiClient.revokeConnection(conn.kind, conn.label);
      toast.success(`${provider.displayName} disconnected.`);
      await refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to revoke';
      toast.error(msg);
    } finally {
      setBusy(null);
    }
  }

  /* --------------------------------------------------------------------- */

  return (
    <div className="space-y-6 p-6 max-w-4xl">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight flex items-center gap-2">
          <Link2 className="w-6 h-6" />
          Connections
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          External accounts your org has connected. Amebo uses these on your behalf when pursuing goals.
        </p>
      </header>

      {connections === null ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : rows.length === 0 ? (
        <Card>
          <CardContent className="p-6 text-sm text-muted-foreground">
            No providers configured yet.
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map(({ provider, connection }) => (
            <ConnectionRow
              key={provider.kind}
              provider={provider}
              connection={connection}
              busy={busy === provider.kind}
              onConnect={() => handleConnect(provider)}
              onRevoke={(c) => handleRevoke(provider, c)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------- */

function ConnectionRow({
  provider,
  connection,
  busy,
  onConnect,
  onRevoke,
}: {
  provider: ProviderDef;
  connection: ConnectionSummary | null;
  busy: boolean;
  onConnect: () => void;
  onRevoke: (c: ConnectionSummary) => void;
}) {
  const isConnected = connection !== null && !connection.revoked_at;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <CardTitle className="text-base flex items-center gap-2">
              {provider.displayName}
              {isConnected ? (
                <Badge variant="default" className="gap-1">
                  <ShieldCheck className="w-3 h-3" />
                  Connected
                </Badge>
              ) : (
                <Badge variant="secondary" className="gap-1">
                  <AlertTriangle className="w-3 h-3" />
                  Not connected
                </Badge>
              )}
            </CardTitle>
            <CardDescription>{provider.description}</CardDescription>
          </div>

          <div className="shrink-0">
            {isConnected && connection ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onRevoke(connection)}
                disabled={busy}
              >
                <Trash2 className="w-4 h-4 mr-1.5" />
                Disconnect
              </Button>
            ) : (
              <Button size="sm" onClick={onConnect} disabled={busy}>
                <Plug className="w-4 h-4 mr-1.5" />
                Connect
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      {isConnected && connection && (
        <CardContent className="text-xs text-muted-foreground space-y-1 pt-0">
          <div className="flex items-center gap-1">
            <Clock className="w-3 h-3" />
            Last used: {fmt(connection.last_used_at)}
          </div>
          <div>Connected: {fmt(connection.created_at)}</div>
          {connection.granted_scopes.length > 0 && (
            <div className="pt-1">
              Scopes:{' '}
              {connection.granted_scopes.map((s) => (
                <code key={s} className="px-1 py-0.5 rounded bg-muted mr-1">{s.split('/').slice(-1)[0]}</code>
              ))}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
