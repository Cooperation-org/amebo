'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Clock, Play, Settings } from 'lucide-react';

interface BackfillSchedulerProps {
  workspaceId: string;
  currentSchedule?: {
    cron_expression: string;
    days_to_backfill: number;
    is_active: boolean;
  };
  onScheduleUpdate?: (schedule: any) => void;
  onManualSync?: () => void;
}

export function BackfillScheduler({ 
  workspaceId, 
  currentSchedule,
  onScheduleUpdate,
  onManualSync 
}: BackfillSchedulerProps) {
  const [schedule, setSchedule] = useState(currentSchedule?.cron_expression || 'daily');
  const [daysBack, setDaysBack] = useState(currentSchedule?.days_to_backfill || 7);
  const [isActive, setIsActive] = useState(currentSchedule?.is_active ?? true);
  const [isUpdating, setIsUpdating] = useState(false);

  const scheduleOptions = [
    { value: '0 2 * * *', label: 'Daily at 2 AM' },
    { value: '0 */6 * * *', label: 'Every 6 hours' },
    { value: '0 * * * *', label: 'Every hour' },
    { value: '*/30 * * * *', label: 'Every 30 minutes' },
    { value: 'custom', label: 'Custom schedule' },
  ];

  const daysBackOptions = [
    { value: 1, label: 'Last 1 day' },
    { value: 7, label: 'Last 7 days' },
    { value: 30, label: 'Last 30 days' },
    { value: 90, label: 'Last 90 days' },
  ];

  const handleSaveSchedule = async () => {
    setIsUpdating(true);
    try {
      const scheduleData = {
        cron_expression: schedule,
        days_to_backfill: daysBack,
        is_active: isActive,
      };
      
      onScheduleUpdate?.(scheduleData);
    } catch (error) {
      console.error('Failed to update schedule:', error);
    } finally {
      setIsUpdating(false);
    }
  };

  const getScheduleDescription = (cronExpr: string) => {
    const option = scheduleOptions.find(opt => opt.value === cronExpr);
    return option?.label || cronExpr;
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Clock className="h-5 w-5" />
          Backfill Schedule
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Manual Sync */}
        <div className="flex items-center justify-between p-4 bg-blue-50 rounded-lg">
          <div>
            <h4 className="font-medium">Manual Sync</h4>
            <p className="text-sm text-gray-600">Trigger an immediate backfill</p>
          </div>
          <Button onClick={onManualSync} variant="outline">
            <Play className="h-4 w-4 mr-2" />
            Sync Now
          </Button>
        </div>

        {/* Schedule Configuration */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="schedule-active">Automatic Backfill</Label>
            <Switch
              id="schedule-active"
              checked={isActive}
              onCheckedChange={setIsActive}
            />
          </div>

          {isActive && (
            <>
              <div className="space-y-2">
                <Label htmlFor="schedule">Schedule</Label>
                <Select value={schedule} onValueChange={setSchedule}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select schedule" />
                  </SelectTrigger>
                  <SelectContent>
                    {scheduleOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-sm text-gray-500">
                  Current: {getScheduleDescription(schedule)}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="days-back">Days to Backfill</Label>
                <Select value={daysBack.toString()} onValueChange={(value) => setDaysBack(parseInt(value))}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select days" />
                  </SelectTrigger>
                  <SelectContent>
                    {daysBackOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value.toString()}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          <Button 
            onClick={handleSaveSchedule} 
            disabled={isUpdating}
            className="w-full"
          >
            <Settings className="h-4 w-4 mr-2" />
            {isUpdating ? 'Saving...' : 'Save Schedule'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}