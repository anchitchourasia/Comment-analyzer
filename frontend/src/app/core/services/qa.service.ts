import { Injectable, inject, signal } from '@angular/core';
import { ApiClientService } from './api-client.service';
import { ToastService } from './toast.service';
import { QaRecord, MatcherTestResult } from '../models/qa.models';
import { tap, catchError } from 'rxjs/operators';
import { of, throwError } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class QaService {
  private api = inject(ApiClientService);
  private toast = inject(ToastService);

  records = signal<QaRecord[]>([]);
  loading = signal<boolean>(false);

  constructor() {
    this.loadMemory();
  }

  loadMemory() {
    this.loading.set(true);
    this.api.get<{ records: QaRecord[] }>('/api/qa/memory').pipe(
      tap((res) => {
        if (res && res.records) {
          this.records.set(res.records);
        }
        this.loading.set(false);
      }),
      catchError(() => {
        this.loading.set(false);
        return of(null);
      })
    ).subscribe();
  }

  saveMemory(question: string, answer: string, autoReply = false) {
    if (!question || !question.trim() || !answer || !answer.trim()) {
      this.toast.error('Validation Error', 'Both question and answer text are required');
      return throwError(() => new Error('Question and answer text are required'));
    }
    return this.api.post<{ status: string; record: QaRecord }>('/api/qa/memory', {
      question: question.trim(),
      answer: answer.trim(),
      auto_reply: autoReply
    }).pipe(
      tap(() => {
        this.toast.success('Q&A Saved 💾', 'Record added to pre-approved memory bank');
        this.loadMemory();
      }),
      catchError((err) => {
        this.toast.error('Save Error', 'Failed to save Q&A record');
        throw err;
      })
    );
  }

  deleteMemory(recordId: string) {
    if (!recordId || !recordId.trim()) {
      this.toast.error('Validation Error', 'Record ID is required');
      return throwError(() => new Error('Record ID is required'));
    }
    return this.api.delete<{ status: string }>(`/api/qa/memory/${recordId.trim()}`).pipe(
      tap(() => {
        this.toast.info('Record Deleted', 'Q&A pair removed from memory bank');
        this.loadMemory();
      }),
      catchError((err) => {
        this.toast.error('Delete Error', 'Failed to delete Q&A record');
        throw err;
      })
    );
  }

  testMatcher(question: string) {
    if (!question || !question.trim()) {
      this.toast.error('Validation Error', 'Question is required for testing matcher');
      return throwError(() => new Error('Question is required'));
    }
    return this.api.post<MatcherTestResult>('/api/qa/test_matcher', { question: question.trim() });
  }
}
