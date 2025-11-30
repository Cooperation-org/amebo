// JWT token management utilities

export interface TokenData {
  access_token: string;
  token_type: string;
  expires_in?: number;
}

export class TokenManager {
  private static readonly TOKEN_KEY = 'auth_token';
  private static readonly REFRESH_KEY = 'refresh_token';
  private static readonly EXPIRY_KEY = 'token_expiry';

  static setTokens(tokenData: TokenData) {
    if (typeof window === 'undefined') return;
    
    const expiryTime = tokenData.expires_in 
      ? Date.now() + (tokenData.expires_in * 1000)
      : Date.now() + (7 * 24 * 60 * 60 * 1000); // Default 7 days for development

    localStorage.setItem(this.TOKEN_KEY, tokenData.access_token);
    localStorage.setItem(this.EXPIRY_KEY, expiryTime.toString());
  }

  static getToken(): string | null {
    if (typeof window === 'undefined') return null;
    
    const token = localStorage.getItem(this.TOKEN_KEY);
    const expiry = localStorage.getItem(this.EXPIRY_KEY);
    
    if (!token) return null;
    
    // For development, be more lenient with expiry
    if (expiry && Date.now() > parseInt(expiry)) {
      // Don't auto-clear in development, just log
      console.warn('Token expired but keeping for development');
    }
    
    return token;
  }

  static clearTokens() {
    if (typeof window === 'undefined') return;
    
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_KEY);
    localStorage.removeItem(this.EXPIRY_KEY);
  }

  static isTokenValid(): boolean {
    return this.getToken() !== null;
  }

  static getAuthHeader(): Record<string, string> {
    const token = this.getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
}