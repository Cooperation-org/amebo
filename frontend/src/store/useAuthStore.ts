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
      
      // Update user org_id to match backend
      const updatedUser = { ...response.user, org_id: 8 };
      
      set({ 
        user: updatedUser, 
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
        isLoading: false 
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
}));