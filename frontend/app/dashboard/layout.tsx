'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ProtectedRoute } from '@/src/components/auth/ProtectedRoute';
import { useAuthStore } from '@/src/store/useAuthStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { User, Settings, LogOut, MessageSquare, Building2, Users, Menu, X, Link2, Inbox } from 'lucide-react';
import { usePermissions } from '@/src/hooks/usePermissions';
import { usePendingActions } from '@/src/hooks/usePendingActions';
import { useNeedsInput } from '@/src/hooks/useNeedsInput';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const { canInviteUsers } = usePermissions();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { data: pendingActions } = usePendingActions();
  const pendingCount = pendingActions?.length ?? 0;
  const { data: needsInput } = useNeedsInput();
  const needsInputCount = needsInput?.length ?? 0;

  // Thin fixed chrome (docs/DASHBOARD.md): wordmark = home; only the few
  // top-level places live here. Q&A/Connections/Team are secondary — they sit
  // in the account dropdown until their pages merge under Workspaces/Settings.
  const navigation = [
    { name: 'Chat', href: '/chat', icon: MessageSquare },
    { name: 'Needs input', href: '/dashboard/needs-input', icon: Inbox },
    { name: 'Workspaces', href: '/dashboard/workspaces', icon: Building2 },
    { name: 'Settings', href: '/dashboard/settings', icon: Settings },
  ];
  const secondary = [
    { name: 'Q&A', href: '/dashboard/qa', icon: MessageSquare },
    { name: 'Connections', href: '/dashboard/connections', icon: Link2 },
    ...(canInviteUsers ? [{ name: 'Team', href: '/dashboard/team', icon: Users }] : []),
  ];

  const handleLogout = async () => {
    await logout();
  };

  return (
    <ProtectedRoute>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-white shadow-sm border-b">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between h-11">
              <div className="flex items-center space-x-8">
                <Link href="/dashboard" className="text-base font-semibold text-gray-900">
                  Amebo
                </Link>
                <span className="text-sm text-gray-500 -ml-4">{user?.org_name}</span>
                <div className="hidden md:flex space-x-4">
                  {[...navigation, ...secondary].map((item) => {
                    const Icon = item.icon;
                    const isActive = pathname === item.href;
                    return (
                      <Link
                        key={item.name}
                        href={item.href}
                        className={`flex items-center px-2.5 py-1 rounded-md text-sm font-medium transition-colors ${
                          isActive
                            ? 'bg-blue-100 text-blue-700'
                            : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        }`}
                      >
                        <Icon className="h-4 w-4 mr-2" />
                        {item.name}
                      </Link>
                    );
                  })}
                </div>
              </div>
              <div className="flex items-center space-x-4">
                {needsInputCount > 0 && (
                  <Link
                    href="/dashboard/needs-input"
                    className="flex items-center gap-1.5 rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800 hover:bg-blue-200"
                  >
                    {needsInputCount} need input
                  </Link>
                )}
                {pendingCount > 0 && (
                  <Link
                    href="/dashboard/approvals"
                    className="flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-200"
                  >
                    {pendingCount} to approve
                  </Link>
                )}
                {/* Mobile hamburger button */}
                <Button
                  variant="ghost"
                  size="sm"
                  className="md:hidden"
                  onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                >
                  {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="sm" className="flex items-center space-x-2">
                      <User className="h-4 w-4" />
                      <span className="hidden sm:block">{user?.email}</span>
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    {secondary.map((item) => {
                      const Icon = item.icon;
                      return (
                        <DropdownMenuItem asChild key={item.name}>
                          <Link href={item.href} className="flex items-center">
                            <Icon className="h-4 w-4 mr-2" />
                            {item.name}
                          </Link>
                        </DropdownMenuItem>
                      );
                    })}
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                      <Link href="/dashboard/settings" className="flex items-center">
                        <Settings className="h-4 w-4 mr-2" />
                        Settings
                      </Link>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={handleLogout} className="flex items-center">
                      <LogOut className="h-4 w-4 mr-2" />
                      Logout
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>
          </div>
        </nav>

        {/* Mobile menu */}
        {mobileMenuOpen && (
          <div className="md:hidden bg-white border-b shadow-sm">
            <div className="px-4 py-2 space-y-1">
              {navigation.map((item) => {
                const Icon = item.icon;
                const isActive = pathname === item.href;
                return (
                  <Link
                    key={item.name}
                    href={item.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className={`flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-blue-100 text-blue-700'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                    }`}
                  >
                    <Icon className="h-4 w-4 mr-2" />
                    {item.name}
                  </Link>
                );
              })}
            </div>
          </div>
        )}

        <main className="max-w-7xl mx-auto py-4 px-4 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </ProtectedRoute>
  );
}