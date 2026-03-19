import { create } from 'zustand';
import { apiClient } from '@/src/lib/api';
import { TokenManager } from '@/src/lib/auth';

interface User {
  user_id: number;
  email: string;
  org_id: number;
  org_name?: string;
  full_name?: string;
  role: string;
  email_verified?: boolean;
}

interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  must_change_password?: boolean;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  requiresPasswordChange: boolean;
  login: (email: string, password: string) => Promise<{ mustChangePassword: boolean }>;
  signup: (email: string, password: string, orgName: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
  clearPasswordChangeRequirement: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isLoading: false,
  isAuthenticated: false,
  requiresPasswordChange: false,

  login: async (email: string, password: string) => {
    set({ isLoading: true });
    try {
      const response = await apiClient.login(email, password) as LoginResponse;

      // Store tokens
      TokenManager.setTokens({
        access_token: response.access_token,
        token_type: response.token_type,
        expires_in: response.expires_in,
      });
      TokenManager.setRefreshToken(response.refresh_token);

      // Fetch actual user data from /me endpoint
      const user = await apiClient.getCurrentUser() as User;

      const mustChangePassword = response.must_change_password || false;

      set({
        user,
        isAuthenticated: true,
        isLoading: false,
        requiresPasswordChange: mustChangePassword,
      });

      return { mustChangePassword };
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  signup: async (email: string, password: string, orgName: string) => {
    set({ isLoading: true });
    try {
      const fullName = email.split('@')[0];
      const response = await apiClient.signup(email, password, orgName, fullName) as LoginResponse;

      // Store tokens
      TokenManager.setTokens({
        access_token: response.access_token,
        token_type: response.token_type,
        expires_in: response.expires_in,
      });
      TokenManager.setRefreshToken(response.refresh_token);

      // Fetch actual user data
      const user = await apiClient.getCurrentUser() as User;

      set({
        user,
        isAuthenticated: true,
        isLoading: false
      });
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  logout: async () => {
    try {
      await apiClient.logout();
    } catch (error) {
      // Continue with logout even if API call fails
    } finally {
      TokenManager.clearTokens();
      set({ 
        user: null, 
        isAuthenticated: false, 
        isLoading: false 
      });
    }
  },

  checkAuth: async () => {
    set({ isLoading: true });
    
    // Check if we have a valid token
    if (!TokenManager.isTokenValid()) {
      set({ 
        user: null, 
        isAuthenticated: false, 
        isLoading: false 
      });
      return;
    }
    
    try {
      const user = await apiClient.getCurrentUser() as User;
      set({
        user,
        isAuthenticated: true,
        isLoading: false,
        requiresPasswordChange: user.email_verified === false,
      });
    } catch (error) {
      // Token is invalid, clear it
      TokenManager.clearTokens();
      set({ 
        user: null, 
        isAuthenticated: false, 
        isLoading: false 
      });
    }
  },

  clearPasswordChangeRequirement: () => {
    set({ requiresPasswordChange: false });
  },
}));