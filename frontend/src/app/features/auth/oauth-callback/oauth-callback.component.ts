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
        localStorage.setItem('session_token', sessionToken);
        this.auth.checkSession();
        this.toast.success('Signed In', 'Welcome to Stream Assistant AI!');
        this.router.navigate(['/dashboard']);
        return;
      }

      if (code && state) {
        this.auth.loginCallback(code, state).subscribe({
          next: () => {
            this.toast.success('Signed In', 'Welcome to Stream Assistant AI!');
            this.router.navigate(['/dashboard']);
          },
          error: (err) => {
            this.toast.error('OAuth Exchange Failed', err.error?.detail || 'Failed to exchange OAuth code.');
            this.router.navigate(['/login']);
          }
        });
      } else {
        this.router.navigate(['/dashboard']);
      }
    });
  }
}
