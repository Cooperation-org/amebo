'use client';

import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Plus, Trash2 } from 'lucide-react';
import { useSetOrgLinks, type OrgLink } from '@/src/hooks/useOrgLinks';

interface EditLinksDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialLinks: OrgLink[];
}

/**
 * Admin-only editor for the org's key links. Writes through the gated
 * PUT /api/organizations/links endpoint (instances.config.links) — links are
 * never hardcoded in the frontend.
 */
export function EditLinksDialog({ open, onOpenChange, initialLinks }: EditLinksDialogProps) {
  const [rows, setRows] = useState<OrgLink[]>(
    initialLinks.length > 0 ? initialLinks : [{ label: '', url: '' }]
  );
  const setLinks = useSetOrgLinks();

  // Re-seed the rows each time the dialog opens: initialLinks is empty at
  // mount (query still loading), so a once-only initializer shows blank rows
  // forever — the add-but-can't-edit bug.
  useEffect(() => {
    if (open) {
      setRows(initialLinks.length > 0 ? initialLinks : [{ label: '', url: '' }]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const updateRow = (i: number, field: keyof OrgLink, value: string) => {
    setRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  };

  const addRow = () => setRows((prev) => [...prev, { label: '', url: '' }]);
  const removeRow = (i: number) => setRows((prev) => prev.filter((_, idx) => idx !== i));

  const handleSave = async () => {
    const cleaned = rows
      .map((r) => ({ label: r.label.trim(), url: r.url.trim() }))
      .filter((r) => r.label && r.url);
    await setLinks.mutateAsync(cleaned);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Your org&apos;s tools</DialogTitle>
          <DialogDescription>
            Links shown across the top of the dashboard. Each opens the tool that owns the work.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <div className="hidden sm:grid grid-cols-[1fr_1.6fr_auto] gap-2 px-1 text-xs font-medium text-gray-500">
            <span>Label</span>
            <span>URL (or /internal path)</span>
            <span />
          </div>
          {rows.map((row, i) => (
            <div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr_1.6fr_auto] gap-2 items-center">
              <Input
                aria-label="Label"
                placeholder="Marten"
                value={row.label}
                onChange={(e) => updateRow(i, 'label', e.target.value)}
              />
              <Input
                aria-label="URL"
                placeholder="https://marten.linkedtrust.us"
                value={row.url}
                onChange={(e) => updateRow(i, 'url', e.target.value)}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeRow(i)}
                aria-label="Remove link"
              >
                <Trash2 className="h-4 w-4 text-gray-400" />
              </Button>
            </div>
          ))}
          <Button type="button" variant="outline" size="sm" onClick={addRow}>
            <Plus className="h-4 w-4 mr-2" />
            Add link
          </Button>
        </div>

        {setLinks.isError && (
          <p className="text-sm text-red-600">Couldn&apos;t save links. Please try again.</p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={setLinks.isPending}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={setLinks.isPending}>
            {setLinks.isPending ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
