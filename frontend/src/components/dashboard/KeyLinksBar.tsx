'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ExternalLink, Pencil, Plus } from 'lucide-react';
import { useOrgLinks, type OrgLink } from '@/src/hooks/useOrgLinks';
import { usePermissions } from '@/src/hooks/usePermissions';
import { EditLinksDialog } from './EditLinksDialog';

function isInternal(url: string) {
  return url.startsWith('/');
}

function LinkButton({ link }: { link: OrgLink }) {
  if (isInternal(link.url)) {
    return (
      <Button asChild variant="outline" className="h-auto py-1.5 px-3 text-sm">
        <Link href={link.url}>{link.label}</Link>
      </Button>
    );
  }
  return (
    <Button asChild variant="outline" className="h-auto py-1.5 px-3 text-sm">
      <a href={link.url} target="_blank" rel="noopener noreferrer">
        {link.label}
        <ExternalLink className="h-3.5 w-3.5 ml-2 text-gray-400" />
      </a>
    </Button>
  );
}

/**
 * The org's key links — the main tools, shown as prominent buttons across the
 * top of the dashboard. Read-only: every button links out to the owning tool.
 * Links come from per-org config (GET/PUT /api/organizations/links), never
 * hardcoded. Empty config shows an admin-only "add your tools" affordance.
 */
export function KeyLinksBar() {
  const { data: links, isLoading } = useOrgLinks();
  const { isAdmin } = usePermissions();
  const [editOpen, setEditOpen] = useState(false);

  return (
    <section aria-label="Key links" className="mb-6">
      {isLoading ? (
        <div className="flex flex-wrap gap-2">
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-8 w-24" />
          <Skeleton className="h-8 w-24" />
        </div>
      ) : links && links.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          {links.map((link, i) => (
            <LinkButton key={`${link.label}-${i}`} link={link} />
          ))}
          {isAdmin && (
            <Button
              variant="ghost"
              size="sm"
              className="text-gray-400 h-7 px-2"
              onClick={() => setEditOpen(true)}
              aria-label="Edit links"
            >
              <Pencil className="h-3.5 w-3.5" />
            </Button>
          )}
        </div>
      ) : isAdmin ? (
        <Button variant="outline" className="h-auto py-1.5 px-3 text-sm" onClick={() => setEditOpen(true)}>
          <Plus className="h-4 w-4 mr-2" />
          Add your org&apos;s tools
        </Button>
      ) : (
        <p className="text-sm text-gray-400">No tools configured yet.</p>
      )}

      {isAdmin && (
        <EditLinksDialog
          open={editOpen}
          onOpenChange={setEditOpen}
          initialLinks={links ?? []}
        />
      )}
    </section>
  );
}
