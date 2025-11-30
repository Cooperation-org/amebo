'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { Slider } from '@/components/ui/slider';
import { Settings, Save, RotateCcw } from 'lucide-react';

export default function SettingsPage() {
  const [settings, setSettings] = useState({
    // AI Configuration
    ai_tone: 'professional',
    ai_response_length: 'balanced',
    confidence_threshold: 40,
    custom_system_prompt: '',
    
    // Data & Privacy
    message_retention_days: 365,
    
    // Notifications
    email_notifications_enabled: true,
    notify_on_failed_backfill: true,
    weekly_digest_enabled: false,
  });

  const [isLoading, setIsLoading] = useState(false);

  const handleSave = async () => {
    setIsLoading(true);
    try {
      // TODO: API call to save settings
      await new Promise(resolve => setTimeout(resolve, 1000));
      console.log('Settings saved:', settings);
    } catch (error) {
      console.error('Failed to save settings:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleReset = () => {
    setSettings({
      ai_tone: 'professional',
      ai_response_length: 'balanced',
      confidence_threshold: 40,
      custom_system_prompt: '',
      message_retention_days: 365,
      email_notifications_enabled: true,
      notify_on_failed_backfill: true,
      weekly_digest_enabled: false,
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-gray-600">Configure AI behavior and organization preferences</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={handleReset}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <Button onClick={handleSave} disabled={isLoading}>
            <Save className="h-4 w-4 mr-2" />
            {isLoading ? 'Saving...' : 'Save Changes'}
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* AI Configuration */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Settings className="h-5 w-5" />
              AI Configuration
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="ai-tone">Response Tone</Label>
              <Select value={settings.ai_tone} onValueChange={(value) => setSettings({...settings, ai_tone: value})}>
                <SelectTrigger>
                  <SelectValue placeholder="Select tone" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="professional">Professional</SelectItem>
                  <SelectItem value="casual">Casual</SelectItem>
                  <SelectItem value="technical">Technical</SelectItem>
                  <SelectItem value="friendly">Friendly</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="response-length">Response Length</Label>
              <Select value={settings.ai_response_length} onValueChange={(value) => setSettings({...settings, ai_response_length: value})}>
                <SelectTrigger>
                  <SelectValue placeholder="Select length" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="concise">Concise</SelectItem>
                  <SelectItem value="balanced">Balanced</SelectItem>
                  <SelectItem value="detailed">Detailed</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-3">
              <Label htmlFor="confidence-threshold">
                Confidence Threshold: {settings.confidence_threshold}%
              </Label>
              <Slider
                value={[settings.confidence_threshold]}
                onValueChange={(value) => setSettings({...settings, confidence_threshold: value[0]})}
                max={100}
                min={0}
                step={5}
                className="w-full"
              />
              <p className="text-sm text-gray-500">
                Minimum confidence required to show answers
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="custom-prompt">Custom System Prompt</Label>
              <Textarea
                id="custom-prompt"
                placeholder="Add custom instructions for the AI assistant..."
                value={settings.custom_system_prompt}
                onChange={(e) => setSettings({...settings, custom_system_prompt: e.target.value})}
                rows={4}
              />
              <p className="text-sm text-gray-500">
                Optional: Customize how the AI responds to questions
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Data & Privacy */}
        <Card>
          <CardHeader>
            <CardTitle>Data & Privacy</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-3">
              <Label htmlFor="retention">
                Message Retention: {settings.message_retention_days} days
              </Label>
              <Slider
                value={[settings.message_retention_days]}
                onValueChange={(value) => setSettings({...settings, message_retention_days: value[0]})}
                max={730}
                min={30}
                step={30}
                className="w-full"
              />
              <p className="text-sm text-gray-500">
                How long to keep Slack messages in the system
              </p>
            </div>

            <div className="p-4 bg-blue-50 rounded-lg">
              <h4 className="font-medium mb-2">Data Management</h4>
              <div className="space-y-2">
                <Button variant="outline" size="sm" className="w-full">
                  Export All Data
                </Button>
                <Button variant="outline" size="sm" className="w-full text-red-600 hover:text-red-700">
                  Delete Old Messages
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Notifications */}
        <Card>
          <CardHeader>
            <CardTitle>Notifications</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="email-notifications">Email Notifications</Label>
                <p className="text-sm text-gray-500">Receive system updates via email</p>
              </div>
              <Switch
                id="email-notifications"
                checked={settings.email_notifications_enabled}
                onCheckedChange={(checked) => setSettings({...settings, email_notifications_enabled: checked})}
              />
            </div>

            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="backfill-notifications">Failed Backfill Alerts</Label>
                <p className="text-sm text-gray-500">Get notified when sync jobs fail</p>
              </div>
              <Switch
                id="backfill-notifications"
                checked={settings.notify_on_failed_backfill}
                onCheckedChange={(checked) => setSettings({...settings, notify_on_failed_backfill: checked})}
              />
            </div>

            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="weekly-digest">Weekly Digest</Label>
                <p className="text-sm text-gray-500">Summary of Q&A activity</p>
              </div>
              <Switch
                id="weekly-digest"
                checked={settings.weekly_digest_enabled}
                onCheckedChange={(checked) => setSettings({...settings, weekly_digest_enabled: checked})}
              />
            </div>
          </CardContent>
        </Card>

        {/* Organization Info */}
        <Card>
          <CardHeader>
            <CardTitle>Organization</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <Label>Organization Name</Label>
              <p className="text-sm text-gray-600 mt-1">Demo Organization</p>
            </div>
            
            <div>
              <Label>Plan</Label>
              <p className="text-sm text-gray-600 mt-1">Free Plan</p>
            </div>

            <div>
              <Label>Created</Label>
              <p className="text-sm text-gray-600 mt-1">November 30, 2025</p>
            </div>

            <Button variant="outline" className="w-full">
              Upgrade Plan
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}