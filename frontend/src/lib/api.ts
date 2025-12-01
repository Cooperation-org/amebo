import { TokenManager } from './auth';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${this.baseURL}${endpoint}`;
    
    const config: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        'ngrok-skip-browser-warning': 'true',
        ...TokenManager.getAuthHeader(),
        ...options.headers,
      },
      mode: 'cors',
      ...options,
    };

    const response = await fetch(url, config);

    if (response.status === 401) {
      const errorData = await response.json().catch(() => ({ message: 'Authentication required' }));
      // Only redirect to login for actual auth failures, not other 401s
      if (errorData.message?.toLowerCase().includes('token') || 
          errorData.message?.toLowerCase().includes('authentication') ||
          errorData.message?.toLowerCase().includes('unauthorized')) {
        TokenManager.clearTokens();
        if (typeof window !== 'undefined') {
          window.location.href = '/login';
        }
      }
      throw new Error(errorData.message || 'Request failed');
    }

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Network error' }));
      throw new Error(error.message || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // Auth endpoints
  async login(email: string, password: string) {
    return this.request('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
  }

  async signup(email: string, password: string, orgName: string, fullName?: string) {
    return this.request('/api/auth/signup', {
      method: 'POST',
      body: JSON.stringify({ 
        email, 
        password, 
        org_name: orgName,
        full_name: fullName || email.split('@')[0] // Use email prefix as default
      }),
    });
  }

  async logout() {
    return this.request('/api/auth/logout', {
      method: 'POST',
    });
  }

  async getCurrentUser() {
    return this.request('/api/auth/me');
  }

  // Q&A endpoints
  async askQuestion(params: {
    question: string;
    workspace_id?: string;
    channel_filter?: string;
    days_back?: number;
    include_documents?: boolean;
    include_slack?: boolean;
    max_sources?: number;
  }) {
    return this.request('/api/qa/ask', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  }

  // Workspace endpoints
  async getWorkspaces() {
    return this.request('/api/workspaces');
  }

  async addWorkspace(data: {
    workspace_name: string;
    bot_token: string;
    app_token: string;
    signing_secret: string;
  }) {
    return this.request('/api/workspaces', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async testWorkspaceConnection(workspaceId: string, credentials?: {
    bot_token: string;
    app_token: string;
    signing_secret: string;
  }) {
    if (credentials) {
      // Test connection with provided credentials (for onboarding)
      return this.request('/api/workspaces/test-connection', {
        method: 'POST',
        body: JSON.stringify(credentials),
      });
    } else {
      // Test existing workspace connection
      return this.request(`/api/workspaces/${workspaceId}/test`);
    }
  }

  async getWorkspaceChannels(workspaceId: string) {
    return this.request(`/api/workspaces/${workspaceId}/channels`);
  }

  async updateWorkspace(workspaceId: string, data: {
    team_name: string;
    bot_token: string;
    app_token: string;
    signing_secret: string;
  }) {
    return this.request(`/api/workspaces/${workspaceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteWorkspace(workspaceId: string) {
    return this.request(`/api/workspaces/${workspaceId}`, {
      method: 'DELETE',
    });
  }

  async syncWorkspace(workspaceId: string) {
    return this.request(`/api/workspaces/${workspaceId}/sync`, {
      method: 'POST',
    });
  }

  async triggerWorkspaceSync(workspaceId: string) {
    return this.request(`/api/workspaces/${workspaceId}/sync`, {
      method: 'POST',
    });
  }

  async triggerBackfill(workspaceId: string, days: number) {
    return this.request(`/api/workspaces/${workspaceId}/backfill`, {
      method: 'POST',
      body: JSON.stringify({ days_back: days }),
    });
  }

  // Team management endpoints
  async getTeamMembers() {
    return this.request('/api/team/members');
  }

  async inviteUser(data: {
    email: string;
    role: string;
  }) {
    return this.request('/api/team/invite', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateUserRole(userId: number, role: string) {
    return this.request(`/api/team/members/${userId}/role`, {
      method: 'PUT',
      body: JSON.stringify({ role }),
    });
  }

  async deactivateUser(userId: number) {
    return this.request(`/api/team/members/${userId}/deactivate`, {
      method: 'PUT',
    });
  }

  async activateUser(userId: number) {
    return this.request(`/api/team/members/${userId}/activate`, {
      method: 'PUT',
    });
  }

  async deleteUser(userId: number) {
    return this.request(`/api/team/members/${userId}`, {
      method: 'DELETE',
    });
  }

  // Document endpoints
  async uploadDocuments(files: File[], workspaceId?: string) {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('files', file);
    });
    if (workspaceId) {
      formData.append('workspace_id', workspaceId);
    }

    const url = `${this.baseURL}/api/documents/upload`;
    const response = await fetch(url, {
      method: 'POST',
      mode: 'cors',
      headers: {
        'ngrok-skip-browser-warning': 'true',
        ...TokenManager.getAuthHeader(),
      },
      body: formData,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ message: 'Upload failed' }));
      throw new Error(error.message || `HTTP ${response.status}`);
    }

    return response.json();
  }

  async getDocuments(workspaceId?: string, page = 1, pageSize = 20) {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    if (workspaceId) {
      params.append('workspace_id', workspaceId);
    }
    return this.request(`/api/documents?${params}`);
  }

  async deleteDocument(documentId: string) {
    return this.request(`/api/documents/${documentId}`, {
      method: 'DELETE',
    });
  }

  async clearAllDocuments() {
    return this.request('/api/documents/clear-all', {
      method: 'DELETE',
    });
  }
}

export const apiClient = new ApiClient(API_BASE_URL);