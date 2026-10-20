import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { toObservable } from '@angular/core/rxjs-interop';
import { filter, map, take } from 'rxjs/operators';
import { Observable } from 'rxjs';

export const authGuard: CanActivateFn = (route, state): boolean | UrlTree | Observable<boolean | UrlTree> => {
  const auth = inject(AuthService);
  const router = inject(Router);

  // If session check already completed
  if (!auth.loading()) {
    return auth.isAuthenticated() ? true : router.createUrlTree(['/login']);
  }

  // If session check is still in-flight, wait until loading completes before evaluating authentication
  return toObservable(auth.loading).pipe(
    filter(loading => !loading),
    take(1),
    map(() => (auth.isAuthenticated() ? true : router.createUrlTree(['/login'])))
  );
};
