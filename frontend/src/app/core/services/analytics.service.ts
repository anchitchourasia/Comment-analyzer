import { Injectable, inject, signal } from '@angular/core';
import { ApiClientService } from './api-client.service';
import { ToastService } from './toast.service';
import { CommentAnalytics } from '../models/analytics.models';
import { tap, catchError } from 'rxjs/operators';
import { throwError } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class AnalyticsService {
  private api = inject(ApiClientService);
  private toast = inject(ToastService);

  analyticsData = signal<CommentAnalytics | null>(null);
  loading = signal<boolean>(false);

  analyzeVideo(videoId: string) {
    if (!videoId || !videoId.trim()) {
      this.toast.error('Validation Error', 'Video ID or URL is required');
      return throwError(() => new Error('Video ID is required'));
    }
    this.loading.set(true);
    return this.api.post<CommentAnalytics>('/api/comments/analyze', { video_id: videoId.trim() }).pipe(
      tap((res) => {
        this.analyticsData.set(res);
        this.loading.set(false);
        this.toast.success('Analytics Complete', `Analyzed ${res.total_comments} comments`);
      }),
      catchError((err) => {
        this.loading.set(false);
        const msg = err.error?.detail || 'Failed to analyze video comments';
        this.toast.error('Analytics Error', msg);
        throw err;
      })
    );
  }
}
