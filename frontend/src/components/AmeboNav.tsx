'use client';

// The one Amebo bar. Every Amebo page mounts this and only this, directly
// under the cohort bar, so a person moving between the inbox, goals and chat
// sees the same row in the same place.
//
// Three places, and that is the whole bar. Golda 2026-08-10: "should be just
// inbox, go right to inbox, and have goals and chat. that's all."
//
// Tasks, CRM and governance belong to the cohort bar above this one, so Amebo
// does not repeat them. Workspaces and Team are settings, not places, and live
// on the settings page; Settings itself is in the account menu, not a tab.
//
// `right` is for controls that belong to the page under the bar (chat's
// conversation list, voice, new) so a page never needs a second row of its own.

import { useState, type ReactNode } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/src/store/useAuthStore';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { User, Settings, LogOut, MessageSquare, Menu, X, Inbox, Target } from 'lucide-react';
import { useWorkList } from '@/src/hooks/useWorkList';

const navigation = [
  { name: 'Inbox', href: '/dashboard/list', icon: Inbox },
  { name: 'Goals', href: '/dashboard/goals', icon: Target },
  { name: 'Chat', href: '/chat', icon: MessageSquare },
];

export function AmeboNav({ right }: { right?: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuthStore();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // One list, one count. Approvals and needs-input forward into it.
  const { data: workList } = useWorkList();
  const listCount = workList?.live.length ?? 0;

  const handleLogout = async () => {
    await logout();
  };

  return (
    <>
      <nav className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-11">
            <div className="flex items-center space-x-8">
              <Link href="/dashboard" className="text-base font-semibold text-gray-900">
                Amebo
              </Link>
              {user?.org_name && (
                <span className="text-sm text-gray-500 -ml-4">{user.org_name}</span>
              )}
              <div className="hidden md:flex space-x-4">
                {navigation.map((item) => {
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
                      {/* How much is waiting, on the place it is waiting. */}
                      {item.href === '/dashboard/list' && listCount > 0 && (
                        <span className="ml-1.5 rounded-full bg-emerald-100 px-1.5 text-xs font-medium text-emerald-900">
                          {listCount}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
            <div className="flex items-center space-x-2">
              {right}
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
    </>
  );
}
