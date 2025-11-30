'use client';

import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Users, UserPlus, MoreHorizontal, Mail, Shield, Eye, Loader2, Trash2, UserX, UserCheck } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator } from '@/components/ui/dropdown-menu';
import { InviteUserModal } from '@/src/components/team/InviteUserModal';
import { useTeamMembers, useUpdateUserRole, useDeactivateUser, useDeleteUser, useActivateUser } from '@/src/hooks/useTeam';
import { toast } from 'sonner';

interface TeamMember {
  user_id: number;
  name: string;
  email: string;
  role: 'admin' | 'member' | 'viewer';
  status: 'active' | 'pending' | 'inactive';
  avatar_url?: string;
  last_active?: string;
  invited_at: string;
}

export default function TeamPage() {
  const [showInviteModal, setShowInviteModal] = useState(false);
  
  const { data: teamData, isLoading } = useTeamMembers();
  const updateRoleMutation = useUpdateUserRole();
  const deactivateUserMutation = useDeactivateUser();
  const activateUserMutation = useActivateUser();
  const deleteUserMutation = useDeleteUser();
  
  const teamMembers = teamData?.members || [];
  
  const handleRoleChange = async (userId: number, newRole: string) => {
    try {
      await updateRoleMutation.mutateAsync({ userId, role: newRole });
      toast.success('User role updated successfully');
    } catch (error) {
      toast.error('Failed to update user role');
    }
  };
  
  const handleDeactivateUser = async (userId: number) => {
    if (confirm('Are you sure you want to deactivate this user? They will be hidden but can be reactivated later.')) {
      try {
        await deactivateUserMutation.mutateAsync(userId);
        toast.success('User deactivated successfully');
      } catch (error) {
        toast.error('Failed to deactivate user');
      }
    }
  };
  
  const handleDeleteUser = async (userId: number) => {
    if (confirm('Are you sure you want to permanently delete this user? This action cannot be undone.')) {
      try {
        await deleteUserMutation.mutateAsync(userId);
        toast.success('User deleted permanently');
      } catch (error) {
        toast.error('Failed to delete user');
      }
    }
  };
  
  const handleActivateUser = async (userId: number) => {
    try {
      await activateUserMutation.mutateAsync(userId);
      toast.success('User activated successfully');
    } catch (error) {
      toast.error('Failed to activate user');
    }
  };

  const getRoleIcon = (role: string) => {
    switch (role) {
      case 'admin':
        return <Shield className="h-4 w-4 text-red-600" />;
      case 'member':
        return <Users className="h-4 w-4 text-blue-600" />;
      case 'viewer':
        return <Eye className="h-4 w-4 text-gray-600" />;
      default:
        return null;
    }
  };

  const getRoleBadge = (role: string) => {
    switch (role) {
      case 'admin':
        return <Badge className="bg-red-100 text-red-800">Admin</Badge>;
      case 'member':
        return <Badge className="bg-blue-100 text-blue-800">Member</Badge>;
      case 'viewer':
        return <Badge className="bg-gray-100 text-gray-800">Viewer</Badge>;
      default:
        return <Badge variant="secondary">{role}</Badge>;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return <Badge className="bg-green-100 text-green-800">Active</Badge>;
      case 'pending':
        return <Badge className="bg-yellow-100 text-yellow-800">Pending</Badge>;
      case 'inactive':
        return <Badge className="bg-gray-100 text-gray-800">Inactive</Badge>;
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Team Management</h1>
          <p className="text-gray-600">Manage users and permissions for your organization</p>
        </div>
        <Button onClick={() => setShowInviteModal(true)}>
          <UserPlus className="h-4 w-4 mr-2" />
          Invite User
        </Button>
      </div>

      {/* Role Descriptions */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Shield className="h-8 w-8 text-red-600" />
              <div>
                <h3 className="font-medium">Admin</h3>
                <p className="text-sm text-gray-600">Full access, can manage users</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Users className="h-8 w-8 text-blue-600" />
              <div>
                <h3 className="font-medium">Member</h3>
                <p className="text-sm text-gray-600">Can use Q&A, upload documents</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Eye className="h-8 w-8 text-gray-600" />
              <div>
                <h3 className="font-medium">Viewer</h3>
                <p className="text-sm text-gray-600">Read-only access to answers</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Team Members */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Team Members ({teamMembers.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin" />
              <span className="ml-2">Loading team members...</span>
            </div>
          ) : (
            <div className="space-y-4">
              {teamMembers.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <Users className="h-8 w-8 mx-auto mb-2 text-gray-400" />
                  <p className="text-sm">No team members yet</p>
                  <p className="text-xs text-gray-400 mt-1">
                    Invite your first team member to get started
                  </p>
                </div>
              ) : (
                teamMembers.map((member) => (
                  <div
                    key={member.user_id}
                    className="flex items-center justify-between p-4 border rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <Avatar>
                        <AvatarImage src={member.avatar_url} />
                        <AvatarFallback>
                          {member.name.split(' ').map(n => n[0]).join('')}
                        </AvatarFallback>
                      </Avatar>
                      
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="font-medium">{member.name}</h4>
                          {getRoleIcon(member.role)}
                        </div>
                        <p className="text-sm text-gray-600">{member.email}</p>
                        {member.last_active && (
                          <p className="text-xs text-gray-500">Last active: {member.last_active}</p>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        {getRoleBadge(member.role)}
                        <div className="mt-1">
                          {getStatusBadge(member.status)}
                        </div>
                      </div>

                      <div className="text-right text-sm text-gray-500">
                        <p>Invited</p>
                        <p>{formatDate(member.invited_at)}</p>
                      </div>

                      <div className="flex items-center gap-2">
                        <Select 
                          defaultValue={member.role}
                          onValueChange={(value) => handleRoleChange(member.user_id, value)}
                          disabled={updateRoleMutation.isPending}
                        >
                          <SelectTrigger className="w-32">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="admin">Admin</SelectItem>
                            <SelectItem value="member">Member</SelectItem>
                            <SelectItem value="viewer">Viewer</SelectItem>
                          </SelectContent>
                        </Select>

                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button 
                              variant="ghost" 
                              size="sm"
                              disabled={deactivateUserMutation.isPending || deleteUserMutation.isPending || activateUserMutation.isPending}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {member.status === 'active' ? (
                              <DropdownMenuItem 
                                onClick={() => handleDeactivateUser(member.user_id)}
                                className="text-orange-600 focus:text-orange-700"
                              >
                                <UserX className="h-4 w-4 mr-2" />
                                Deactivate User
                              </DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem 
                                onClick={() => handleActivateUser(member.user_id)}
                                className="text-green-600 focus:text-green-700"
                              >
                                <UserCheck className="h-4 w-4 mr-2" />
                                Activate User
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem 
                              onClick={() => handleDeleteUser(member.user_id)}
                              className="text-red-600 focus:text-red-700"
                            >
                              <Trash2 className="h-4 w-4 mr-2" />
                              Delete Permanently
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <InviteUserModal
        open={showInviteModal}
        onClose={() => setShowInviteModal(false)}
        onUserInvited={() => {
          setShowInviteModal(false);
        }}
      />
    </div>
  );
}