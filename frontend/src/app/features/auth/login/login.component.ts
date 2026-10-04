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

  onGoogleLogin() {
    this.loading = true;
    this.auth.loginInit().subscribe({
      error: () => this.loading = false
    });
  }

  onManualLogin() {
    this.auth.setManualMode();
  }
}
