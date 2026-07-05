'use client';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ExternalLink } from 'lucide-react';
import { useOrgBoard } from '@/src/hooks/useOrgBoard';
import type { BoardItem } from '@/src/lib/api';

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  won: 'bg-green-100 text-green-800',
  exploring: 'bg-amber-100 text-amber-800',
  paused: 'bg-gray-100 text-gray-600',
  dropped: 'bg-gray-100 text-gray-500',
};

function StatusBadge({ status }: { status: string }) {
  if (!status) return null;
  const key = status.toLowerCase();
  const cls = STATUS_STYLES[key] || 'bg-blue-100 text-blue-800';
  return <Badge className={`${cls} border-0 capitalize`}>{status}</Badge>;
}

function LinkChip({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:text-blue-900 hover:underline"
    >
      {children}
      <ExternalLink className="h-3 w-3" />
    </a>
  );
}

function isUrl(v: string) {
  return /^https?:\/\//.test(v);
}

function CampaignCard({ item }: { item: BoardItem }) {
  // crm_url (when present) is the campaign's own record in the CRM, resolved by
  // the backend; we only link when we have that specific record (never the
  // generic CRM). taiga only when it's a real URL.
  const crmUrl = item.crm_url || undefined;
  const taigaUrl = isUrl(item.taiga) ? item.taiga : undefined;

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base leading-snug">{item.name}</CardTitle>
          <StatusBadge status={item.status} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col flex-1 gap-3">
        {item.one_liner && <p className="text-sm text-gray-600">{item.one_liner}</p>}
        {item.owner && (
          <p className="text-xs text-gray-500">
            Owner: <span className="text-gray-700">{item.owner}</span>
          </p>
        )}
        <div className="mt-auto flex flex-wrap gap-x-4 gap-y-1.5 pt-1">
          {item.main_md_url && <LinkChip href={item.main_md_url}>MAIN.md</LinkChip>}
          {crmUrl && <LinkChip href={crmUrl}>CRM</LinkChip>}
          {taigaUrl && <LinkChip href={taigaUrl}>Taiga</LinkChip>}
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The campaigns board — one card per live campaign, read from the org's context
 * repo via GET /api/organizations/board. Read-only: every card links out to the
 * tool that owns the thing (the MAIN.md on the git host, the CRM, Taiga). Hidden
 * entirely when there is no board or no items (never a blank placeholder).
 */
export function CampaignsBoard() {
  const { data, isLoading } = useOrgBoard();

  if (isLoading) return null;
  const items = data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section aria-label="Campaigns" className="mt-8">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
        Campaigns
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
        {items.map((item) => (
          <CampaignCard key={item.slug} item={item} />
        ))}
      </div>
    </section>
  );
}
