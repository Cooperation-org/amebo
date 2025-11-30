import { create } from 'zustand';
import { apiClient } from '@/src/lib/api';
import { TokenManager } from '@/src/lib/auth';

interface User {
  user_id: number;
  email: string;
  org_id: number;
  org_name: string;
  role: string;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, orgName: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  isLoading: false,
  isAuthenticated: false,

  login: async (email: string, password: string) => {
    set({ isLoading: true });
    try {
      const response = await apiClient.login(email, password) as { user: User; access_token: string; token_type: string };
      
      // Store JWT token
      TokenManager.setTokens({
        access_token: response.access_token,
        token_type: response.token_type,
      });
      
      set({ 
        user: response.user, 
        isAuthenticated: true, 
        isLoading: false 
      });
    } catch (error) {
      set({ isLoading: false });
      throw error;
    }
  },

  signup: async (email: string, password: string, orgName: string) => {
    set({ isLoading: true });
    try {
      const fullName = email.split('@')[0]; // Use email prefix as default name
      const response = await apiClient.signup(email, password, orgName, fullName) as { user: User; access_token: string; token_type: string };
      
      // Store JWT token
      TokenManager.setTokens({
        access_token: response.access_token,
        token_type: response.token_type,
      });
      
      set({ 
        user: response.user, 
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
    
    // For development, auto-login if no token exists
    if (!TokenManager.isTokenValid()) {
      try {
        // Auto-login with development credentials
        await get().login('orjienekenechukwu@gmail.com', 'Lekan2904.');
        return;
      } catch (error) {
        // If auto-login fails, set mock token for development
        TokenManager.setTokens({
          access_token: 'dev-token-' + Date.now(),
          token_type: 'bearer'
        });
      }
    }
    
    try {
      const user = await apiClient.getCurrentUser() as User;
      set({ 
        user, 
        isAuthenticated: true, 
        isLoading: false 
      });
    } catch (error) {
      // For development, create mock user instead of clearing tokens
      const mockUser: User = {
        user_id: 1,
        email: 'orjienekenechukwu@gmail.com',
        org_id: 1,
        org_name: 'WhatsCookin Team',
        role: 'admin'
      };
      
      set({ 
        user: mockUser, 
        isAuthenticated: true, 
        isLoading: false 
      });
    }
  },
}));