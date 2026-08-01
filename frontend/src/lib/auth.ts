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

  /**
   * When it runs out is written inside the token, so read it there rather than
   * being told. Callers that guessed were saying one hour while the session was
   * good for a month, which would have signed people out mid-work the moment
   * anything started believing the stored number.
   */
  private static expiryFromJwt(token: string): number | null {
    try {
      const payload = token.split('.')[1];
      if (!payload) return null;
      const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
      const exp = JSON.parse(json)?.exp;
      return typeof exp === 'number' ? exp * 1000 : null;
    } catch {
      return null; // Not ours to interpret; fall back to what we were given.
    }
  }

  static setTokens(tokenData: TokenData) {
    if (typeof window === 'undefined') return;

    const expiryTime =
      this.expiryFromJwt(tokenData.access_token) ??
      (tokenData.expires_in
        ? Date.now() + tokenData.expires_in * 1000
        : Date.now() + 60 * 60 * 1000);

    localStorage.setItem(this.TOKEN_KEY, tokenData.access_token);
    localStorage.setItem(this.EXPIRY_KEY, expiryTime.toString());
  }

  static setRefreshToken(token: string) {
    if (typeof window === 'undefined') return;
    localStorage.setItem(this.REFRESH_KEY, token);
  }

  static getRefreshToken(): string | null {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem(this.REFRESH_KEY);
  }

  static getToken(): string | null {
    if (typeof window === 'undefined') return null;

    const token = localStorage.getItem(this.TOKEN_KEY);
    if (!token) return null;

    return token;
  }

  static isTokenExpired(): boolean {
    if (typeof window === 'undefined') return true;
    const expiry = localStorage.getItem(this.EXPIRY_KEY);
    if (!expiry) return false;
    return Date.now() > parseInt(expiry);
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