'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Download, Loader2 } from 'lucide-react';
import { useTriggerBackfill } from '@/src/hooks/useWorkspaces';
import { toast } from 'sonner';

interface BackfillButtonProps {
  workspaceId: string;
  disabled?: boolean;
}

export function BackfillButton({ workspaceId, disabled = false }: BackfillButtonProps) {
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(30);
  
  const backfillMutation = useTriggerBackfill();

  const handleBackfill = async () => {
    try {
      await backfillMutation.mutateAsync({ workspaceId, days });
      toast.success(`Backfill started for ${days} days of messages`);
      setOpen(false);
    } catch (error) {
      toast.error('Failed to start backfill');
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          <Download className="h-4 w-4 mr-2" />
          Backfill
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Backfill Messages</DialogTitle>
        </DialogHeader>
        
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="days">Days to backfill</Label>
            <Input
              id="days"
              type="number"
              min="1"
              max="365"
              value={days}
              onChange={(e) => setDays(parseInt(e.target.value) || 30)}
              placeholder="30"
            />
            <p className="text-sm text-gray-600">
              Number of days of message history to collect (1-365)
            </p>
          </div>
          
          <div className="flex gap-2 pt-4">
            <Button
              variant="outline"
              onClick={() => setOpen(false)}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              onClick={handleBackfill}
              disabled={backfillMutation.isPending || days < 1 || days > 365}
              className="flex-1"
            >
              {backfillMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Starting...
                </>
              ) : (
                <>
                  <Download className="h-4 w-4 mr-2" />
                  Start Backfill
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}