import { Component, inject, OnInit, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, ActivatedRoute } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './login.component.html',
  styleUrl: './login.component.css'
})
export class LoginComponent implements OnInit {
  auth = inject(AuthService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  loading = false;
  errorMessage: string | null = null;

  constructor() {
    // Reactively navigate to dashboard as soon as auth verification completes
    effect(() => {
      if (!this.auth.loading() && this.auth.isAuthenticated()) {
        this.router.navigate(['/dashboard']);
      }
    });
  }

  ngOnInit() {
    this.route.queryParams.subscribe(params => {
      const authError = params['auth_error'] || params['error'];
      if (authError) {
        if (authError === 'invalid_state') {
          this.errorMessage = 'Google sign-in timed out or was interrupted. Please click "Continue with Google Account" to try again.';
        } else if (authError === 'oauth_failed') {
          this.errorMessage = 'Google authorization exchange failed. Please verify your Google account or try again.';
        } else {
          this.errorMessage = `Sign-in notice: ${authError}`;
        }
      }
    });
  }

  onGoogleLogin() {
    this.loading = true;
    this.errorMessage = null;
    this.auth.loginInit().subscribe({
      error: (err) => {
        this.loading = false;
        if (err.status === 503) {
          this.errorMessage = 'Google Sign-In is not configured yet on this server. Click "Continue in Manual Local Video Mode" below to enter immediately, or add GOOGLE_CLIENT_ID to Render.';
        } else {
          this.errorMessage = 'Login failed. Please click "Continue in Manual Local Video Mode" below.';
        }
      }
    });
  }

  onManualLogin() {
    this.auth.setManualMode();
  }
}
