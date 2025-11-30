'use client';

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent } from '@/components/ui/card';
import { Mail, Loader2, CheckCircle, Users, Shield, Eye } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useInviteUser } from '@/src/hooks/useTeam';
import { toast } from 'sonner';

const inviteSchema = z.object({
  email: z.string().email('Please enter a valid email address'),
  role: z.enum(['admin', 'member', 'viewer']),
});

type InviteFormData = z.infer<typeof inviteSchema>;

interface InviteUserModalProps {
  open: boolean;
  onClose: () => void;
  onUserInvited?: () => void;
}

export function InviteUserModal({ open, onClose, onUserInvited }: InviteUserModalProps) {
  const [inviteSent, setInviteSent] = useState(false);
  const [inviteMessage, setInviteMessage] = useState('');
  
  const inviteUserMutation = useInviteUser();

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
    setValue,
    watch,
  } = useForm<InviteFormData>({
    resolver: zodResolver(inviteSchema),
    defaultValues: {
      role: 'member',
    },
  });

  const selectedRole = watch('role');

  const onSubmit = async (data: InviteFormData) => {
    try {
      const response = await inviteUserMutation.mutateAsync({
        email: data.email,
        role: data.role,
      });
      
      setInviteMessage(response.message);
      setInviteSent(true);
      toast.success('User invited successfully!');
      
      setTimeout(() => {
        onUserInvited?.();
        handleClose();
      }, 3000);
    } catch (error) {
      console.error('Failed to send invitation:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to send invitation');
    }
  };

  const handleClose = () => {
    onClose();
    reset();
    setInviteSent(false);
    setInviteMessage('');
  };

  const getRoleDescription = (role: string) => {
    switch (role) {
      case 'admin':
        return 'Full access including user management, settings, and billing';
      case 'member':
        return 'Can ask questions, upload documents, and view all answers';
      case 'viewer':
        return 'Read-only access to view answers and search results';
      default:
        return '';
    }
  };

  const getRoleIcon = (role: string) => {
    switch (role) {
      case 'admin':
        return <Shield className="h-5 w-5 text-red-600" />;
      case 'member':
        return <Users className="h-5 w-5 text-blue-600" />;
      case 'viewer':
        return <Eye className="h-5 w-5 text-gray-600" />;
      default:
        return null;
    }
  };

  if (inviteSent) {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="sm:max-w-md">
          <div className="text-center py-6">
            <CheckCircle className="h-16 w-16 mx-auto text-green-600 mb-4" />
            <h3 className="text-lg font-semibold mb-2">Invitation Sent!</h3>
            <p className="text-gray-600 mb-4">
              {inviteMessage || "We've sent an invitation email with instructions to join your team."}
            </p>
            <Button onClick={handleClose} className="w-full">
              Done
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="h-5 w-5" />
            Invite Team Member
          </DialogTitle>
        </DialogHeader>
        
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email Address</Label>
            <Input
              id="email"
              type="email"
              placeholder="colleague@company.com"
              {...register('email')}
            />
            {errors.email && (
              <p className="text-sm text-red-600">{errors.email.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <Select
              value={selectedRole}
              onValueChange={(value) => setValue('role', value as any)}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a role" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="admin">
                  <div className="flex items-center gap-2">
                    <Shield className="h-4 w-4 text-red-600" />
                    Admin
                  </div>
                </SelectItem>
                <SelectItem value="member">
                  <div className="flex items-center gap-2">
                    <Users className="h-4 w-4 text-blue-600" />
                    Member
                  </div>
                </SelectItem>
                <SelectItem value="viewer">
                  <div className="flex items-center gap-2">
                    <Eye className="h-4 w-4 text-gray-600" />
                    Viewer
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
            {errors.role && (
              <p className="text-sm text-red-600">{errors.role.message}</p>
            )}
          </div>

          {/* Role Description */}
          {selectedRole && (
            <Card className="bg-gray-50">
              <CardContent className="pt-4">
                <div className="flex items-start gap-3">
                  {getRoleIcon(selectedRole)}
                  <div>
                    <h4 className="font-medium capitalize">{selectedRole}</h4>
                    <p className="text-sm text-gray-600 mt-1">
                      {getRoleDescription(selectedRole)}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          <div className="flex gap-2 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={inviteUserMutation.isPending}
              className="flex-1"
            >
              {inviteUserMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Mail className="h-4 w-4 mr-2" />
                  Send Invite
                </>
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}