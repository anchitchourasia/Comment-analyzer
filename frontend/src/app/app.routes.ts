import { Routes } from '@angular/router';
import { LoginComponent } from './features/auth/login/login.component';
import { OauthCallbackComponent } from './features/auth/oauth-callback/oauth-callback.component';
import { DashboardComponent } from './features/dashboard/dashboard.component';
import { LiveQaComponent } from './features/live-qa/live-qa.component';
import { QaLibraryComponent } from './features/qa-library/qa-library.component';
import { AnalyticsComponent } from './features/analytics/analytics.component';
import { SettingsComponent } from './features/settings/settings.component';
import { authGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  { path: '', redirectTo: 'login', pathMatch: 'full' },
  { path: 'login', component: LoginComponent },
  { path: 'oauth-callback', component: OauthCallbackComponent },
  { path: 'auth/callback', component: OauthCallbackComponent },
  { path: 'dashboard', component: DashboardComponent, canActivate: [authGuard] },
  { path: 'live-qa', component: LiveQaComponent, canActivate: [authGuard] },
  { path: 'qa-library', component: QaLibraryComponent, canActivate: [authGuard] },
  { path: 'analytics', component: AnalyticsComponent, canActivate: [authGuard] },
  { path: 'settings', component: SettingsComponent, canActivate: [authGuard] },
  { path: '**', redirectTo: 'login' }
];
