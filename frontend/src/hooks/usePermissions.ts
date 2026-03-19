import { useAuthStore } from '@/src/store/useAuthStore';

type Role = 'owner' | 'admin' | 'member' | 'viewer';

const ROLE_HIERARCHY: Record<Role, number> = {
  owner: 4,
  admin: 3,
  member: 2,
  viewer: 1,
};

function hasMinRole(userRole: string | undefined, minRole: Role): boolean {
  if (!userRole) return false;
  return (ROLE_HIERARCHY[userRole as Role] ?? 0) >= ROLE_HIERARCHY[minRole];
}

export function usePermissions() {
  const { user } = useAuthStore();
  const role = (user?.role ?? 'viewer') as Role;

  return {
    role,

    // Page-level access
    canAccessTeam: true, // all roles can view team list
    canAccessSettings: true,

    // Q&A
    canAskQuestions: hasMinRole(role, 'member'),

    // Documents
    canUploadDocuments: hasMinRole(role, 'member'),
    canDeleteDocuments: hasMinRole(role, 'member'),
    canClearAllDocuments: hasMinRole(role, 'admin'),

    // Workspaces
    canAddWorkspace: hasMinRole(role, 'admin'),
    canEditWorkspace: hasMinRole(role, 'admin'),
    canDeleteWorkspace: hasMinRole(role, 'owner'),
    canSyncWorkspace: hasMinRole(role, 'admin'),

    // Team
    canInviteUsers: hasMinRole(role, 'admin'),
    canChangeRoles: hasMinRole(role, 'admin'),
    canAssignOwnerRole: role === 'owner',
    canDeactivateUsers: hasMinRole(role, 'admin'),
    canDeleteUsers: hasMinRole(role, 'admin'),

    // Settings
    canChangeAISettings: hasMinRole(role, 'admin'),
    canChangeOrgSettings: hasMinRole(role, 'owner'),

    // General
    isAdmin: hasMinRole(role, 'admin'),
    isOwner: role === 'owner',
  };
}
