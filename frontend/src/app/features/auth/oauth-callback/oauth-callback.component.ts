import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { ToastService } from '../../../core/services/toast.service';

@Component({
  selector: 'app-oauth-callback',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './oauth-callback.component.html',
  styleUrl: './oauth-callback.component.css'
})
export class OauthCallbackComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private auth = inject(AuthService);
  private toast = inject(ToastService);

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      const sessionToken = params['session_token'];
      const code = params['code'];
      const state = params['state'];
      const error = params['error'] || params['auth_error'];

      if (error) {
        this.toast.error('Authentication Error', 'Google authorization was denied or failed.');
        this.router.navigate(['/login']);
        return;
      }

      if (sessionToken) {
        this.auth.checkSession(sessionToken).subscribe({
          next: (user) => {
            if (user) {
              this.toast.success('Signed In', `Welcome back, ${user.account_label || 'Creator'}!`);
              this.router.navigate(['/dashboard']);
            } else {
              this.toast.error('Session Error', 'Could not establish session. Please log in again.');
              this.router.navigate(['/login']);
            }
          },
          error: () => {
            this.toast.error('Session Error', 'Could not establish session. Please log in again.');
            this.router.navigate(['/login']);
          }
        });
        return;
      }

      if (code && state) {
        this.auth.loginCallback(code, state).subscribe({
          next: (user) => {
            if (user) {
              this.toast.success('Signed In', 'Welcome to Stream Assistant AI!');
              this.router.navigate(['/dashboard']);
            } else {
              this.toast.error('Authentication Error', 'Failed to verify session. Please log in again.');
              this.router.navigate(['/login']);
            }
          },
          error: (err) => {
            this.toast.error('OAuth Exchange Failed', err.error?.detail || 'Failed to exchange OAuth code.');
            this.router.navigate(['/login']);
          }
        });
        return;
      }

      if (this.auth.isAuthenticated()) {
        this.router.navigate(['/dashboard']);
      } else {
        this.router.navigate(['/login']);
      }
    });
  }
}
