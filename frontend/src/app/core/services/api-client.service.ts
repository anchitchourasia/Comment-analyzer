import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../../environments/environment';

@Injectable({
  providedIn: 'root'
})
export class ApiClientService {
  private http = inject(HttpClient);
  private baseUrl = environment.apiUrl;

  private getOptions(params?: HttpParams, extraHeaders?: { [key: string]: string }) {
    let headers = new HttpHeaders();
    const token = localStorage.getItem('session_token');
    if (token) {
      headers = headers.set('x-session-token', token);
    }
    if (extraHeaders) {
      Object.keys(extraHeaders).forEach(key => {
        headers = headers.set(key, extraHeaders[key]);
      });
    }
    return {
      headers,
      params,
      withCredentials: true
    };
  }

  /**
   * Development-safe error logger.
   * Logs endpoint name, HTTP status code, and sanitized error messages.
   * Never logs authorization headers, cookies, tokens, or private credentials.
   */
  private logSafeError(method: string, endpoint: string, err: HttpErrorResponse) {
    const status = err.status || 'Unknown';
    const detail = err.error?.detail || err.message || 'No details';

    if (status === 422) {
      console.warn(
        `[API Contract Diagnostic] 422 Unprocessable Entity at ${method.toUpperCase()} ${endpoint}. ` +
        `Inspect request schema at http://localhost:8000/docs or browser DevTools Network -> Response tab.`
      );
    } else if (status === 401 || status === 403) {
      console.warn(`[Auth Diagnostic] ${status} Access Restricted at ${method.toUpperCase()} ${endpoint}:`, detail);
    } else {
      console.warn(`[API Diagnostic] ${method.toUpperCase()} ${endpoint} -> Status ${status}:`, detail);
    }
  }

  get<T>(endpoint: string, params?: HttpParams): Observable<T> {
    return this.http.get<T>(`${this.baseUrl}${endpoint}`, this.getOptions(params)).pipe(
      catchError((err: HttpErrorResponse) => {
        this.logSafeError('GET', endpoint, err);
        return throwError(() => err);
      })
    );
  }

  post<T>(endpoint: string, body: any): Observable<T> {
    return this.http.post<T>(`${this.baseUrl}${endpoint}`, body, this.getOptions()).pipe(
      catchError((err: HttpErrorResponse) => {
        this.logSafeError('POST', endpoint, err);
        return throwError(() => err);
      })
    );
  }

  delete<T>(endpoint: string): Observable<T> {
    return this.http.delete<T>(`${this.baseUrl}${endpoint}`, this.getOptions()).pipe(
      catchError((err: HttpErrorResponse) => {
        this.logSafeError('DELETE', endpoint, err);
        return throwError(() => err);
      })
    );
  }
}
