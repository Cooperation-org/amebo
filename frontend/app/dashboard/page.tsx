'use client';

import Link from 'next/link';
import { useAuthStore } from '@/src/store/useAuthStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { MessageSquare, Building2, Settings, Users, Plus, BarChart3 } from 'lucide-react';

export default function DashboardPage() {
  const { user } = useAuthStore();

  const quickActions = [
    {
      title: 'Ask a Question',
      description: 'Get answers from your Slack conversations',
      href: '/dashboard/qa',
      icon: MessageSquare,
      primary: true,
    },
    {
      title: 'Add Workspace',
      description: 'Connect a new Slack workspace',
      href: '/onboarding',
      icon: Plus,
      primary: false,
    },
    {
      title: 'Manage Workspaces',
      description: 'View and configure your workspaces',
      href: '/dashboard/workspaces',
      icon: Building2,
      primary: false,
    },
    {
      title: 'Team Management',
      description: 'Invite users and manage roles',
      href: '/dashboard/team',
      icon: Users,
      primary: false,
    },
    {
      title: 'Settings',
      description: 'Configure AI behavior and preferences',
      href: '/dashboard/settings',
      icon: Settings,
      primary: false,
    },
    {
      title: 'Analytics',
      description: 'View usage statistics and insights',
      href: '/dashboard/analytics',
      icon: BarChart3,
      primary: false,
    },
  ];

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">
          Welcome back!
        </h1>
        <p className="mt-2 text-gray-600">
          {user?.org_name} • {user?.email}
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center">
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-600">Total Workspaces</p>
                <p className="text-2xl font-bold text-gray-900">0</p>
              </div>
              <Building2 className="h-8 w-8 text-blue-600" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center">
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-600">Messages Indexed</p>
                <p className="text-2xl font-bold text-gray-900">0</p>
              </div>
              <MessageSquare className="h-8 w-8 text-green-600" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center">
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-600">Questions Asked</p>
                <p className="text-2xl font-bold text-gray-900">0</p>
              </div>
              <BarChart3 className="h-8 w-8 text-purple-600" />
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center">
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-600">Team Members</p>
                <p className="text-2xl font-bold text-gray-900">1</p>
              </div>
              <Users className="h-8 w-8 text-orange-600" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions */}
      <div className="mb-8">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {quickActions.map((action) => {
            const Icon = action.icon;
            return (
              <Card key={action.title} className="hover:shadow-md transition-shadow">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Icon className="h-5 w-5" />
                    {action.title}
                  </CardTitle>
                  <CardDescription>{action.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <Button 
                    asChild 
                    className="w-full" 
                    variant={action.primary ? 'default' : 'outline'}
                  >
                    <Link href={action.href}>{action.title}</Link>
                  </Button>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Recent Activity */}
      <div>
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Recent Activity</h2>
        <Card>
          <CardContent className="p-6">
            <div className="text-center py-8">
              <MessageSquare className="h-12 w-12 text-gray-400 mx-auto mb-4" />
              <p className="text-gray-600">No recent activity yet.</p>
              <p className="text-sm text-gray-500 mt-1">
                Connect a workspace to start seeing your Q&A history.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}