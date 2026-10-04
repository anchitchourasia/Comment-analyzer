import { Injectable, inject, signal, computed } from '@angular/core';
import { Router } from '@angular/router';
import { ApiClientService } from './api-client.service';
import { UserSession, LoginInitResponse, OAuthInitResponse, ChannelSelectResponse } from '../models/auth.models';
import { catchError, of, tap } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private api = inject(ApiClientService);
  private router = inject(Router);

  // Angular Signals for Authentication State
  user = signal<UserSession | null>(null);
  loading = signal<boolean>(true);
  error = signal<string | null>(null);

  isAuthenticated = computed(() => !!this.user());
  hasChannelSelected = computed(() => !!this.user()?.selected_channel_id);

  constructor() {
    this.checkSession();
  }

  checkSession() {
    this.loading.set(true);

    // Extract session_token from URL query parameters if redirected from backend OAuth
    try {
      const urlParams = new URLSearchParams(window.location.search);
      const urlToken = urlParams.get('session_token');
      if (urlToken) {
        localStorage.setItem('session_token', urlToken);
        const cleanUrl = window.location.pathname + window.location.hash;
        window.history.replaceState({}, document.title, cleanUrl);
      }
    } catch (e) {}

    const token = localStorage.getItem('session_token');
    if (!token) {
      this.demoLogin().subscribe(() => {
        this.loading.set(false);
      });
      return;
    }

    this.api.get<UserSession>('/api/me').pipe(
      tap((session) => {
        if (session) {
          this.user.set(session);
        } else {
          this.user.set(null);
        }
        this.loading.set(false);
      }),
      catchError(() => {
        this.demoLogin().subscribe(() => {
          this.loading.set(false);
        });
        return of(null);
      })
    ).subscribe();
  }

  demoLogin() {
    return this.api.post<{ status: string; session_token: string; user_id: string }>('/api/auth/demo_login', {}).pipe(
      tap((res) => {
        if (res && res.session_token) {
          localStorage.setItem('session_token', res.session_token);
        }
        this.setDefaultDemoUser();
      }),
      catchError(() => {
        this.setDefaultDemoUser();
        return of(null);
      })
    );
  }

  private setDefaultDemoUser() {
    if (!localStorage.getItem('session_token')) {
      localStorage.setItem('session_token', 'demo_session_local_creator');
    }
    // Provide a valid local session so dashboard routes load seamlessly
    const defaultSession: UserSession = {
      user_id: 'local_creator_123',
      account_label: 'Local Streamer (Dev Mode)',
      selected_channel_id: 'UC_DEMO_CHANNEL',
      selected_channel_title: 'Demo Live Channel',
      channel_connection_status: 'connected',
      has_write_scope: true,
      verified_channels: ['UC_DEMO_CHANNEL'],
      channel_titles: { 'UC_DEMO_CHANNEL': 'Demo Live Channel' }
    };
    this.user.set(defaultSession);
  }

  setManualMode() {
    this.demoLogin().subscribe(() => {
      this.router.navigate(['/dashboard']);
    });
  }

  loginInit() {
    return this.api.get<LoginInitResponse>('/api/auth/login/init').pipe(
      tap((res) => {
        if (res.auth_url) {
          window.location.href = res.auth_url;
        }
      })
    );
  }

  loginCallback(code: string, state: string) {
    return this.api.post<{ status: string; session_token: string; user_id: string }>('/api/auth/login/callback', { code, state }).pipe(
      tap((res) => {
        if (res.session_token) {
          localStorage.setItem('session_token', res.session_token);
        }
        this.checkSession();
      })
    );
  }

  oauthInit() {
    return this.api.get<OAuthInitResponse>('/api/oauth/init').pipe(
      tap((res) => {
        if (res.auth_url) {
          window.location.href = res.auth_url;
        }
      })
    );
  }

  selectChannel(channelId: string) {
    return this.api.post<ChannelSelectResponse>('/api/oauth/select_channel', { channel_id: channelId }).pipe(
      tap(() => {
        this.checkSession();
      })
    );
  }

  disconnectChannel() {
    return this.api.post<{ status: string }>('/api/oauth/disconnect', {}).pipe(
      tap(() => {
        this.checkSession();
      })
    );
  }

  logout() {
    return this.api.post<{ status: string }>('/api/auth/logout', {}).pipe(
      tap(() => {
        localStorage.removeItem('session_token');
        this.user.set(null);
        this.router.navigate(['/login']);
      }),
      catchError(() => {
        localStorage.removeItem('session_token');
        this.user.set(null);
        this.router.navigate(['/login']);
        return of({ status: 'logged_out' });
      })
    );
  }
}
