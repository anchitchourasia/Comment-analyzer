import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './login.component.html',
  styleUrl: './login.component.css'
})
export class LoginComponent {
  auth = inject(AuthService);
  loading = false;
  errorMessage: string | null = null;

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
