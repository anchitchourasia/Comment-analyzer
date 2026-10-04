import { Injectable, inject, signal, computed, OnDestroy } from '@angular/core';
import { ApiClientService } from './api-client.service';
import { ToastService } from './toast.service';
import { AuthService } from './auth.service';
import {
  AssistantStatusDto,
  FeedResponseDto,
  PendingQuestionsResponseDto,
  SuggestionsResponseDto,
  SuperchatsResponseDto,
  PostRequestPayload,
  PostResponsePayload,
  ChatFeedItemVM,
  PendingQuestionVM,
  SuggestionItemVM,
  SuperchatAlertVM,
  mapFeedMessage,
  mapPendingQuestion,
  mapSuggestion,
  mapSuperchat
} from '../models/assistant.models';
import { Subscription, timer, of, forkJoin, throwError } from 'rxjs';
import { catchError, exhaustMap, tap, filter } from 'rxjs/operators';

@Injectable({
  providedIn: 'root'
})
export class AssistantService implements OnDestroy {
  private api = inject(ApiClientService);
  private toast = inject(ToastService);
  private auth = inject(AuthService);

  // Reactive State Signals (Clean View Models)
  status = signal<AssistantStatusDto>({
    state: 'IDLE',
    auto_reply: false,
    ignored_names: [],
    ignored_ids: []
  });

  pendingQuestions = signal<{ [key: string]: PendingQuestionVM }>({});
  recentMessages = signal<ChatFeedItemVM[]>([]);
  suggestions = signal<SuggestionItemVM[]>([]);
  superchats = signal<SuperchatAlertVM[]>([]);

  // Computed Confidence Categories for Suggestions
  highConfidenceSuggestions = computed(() =>
    this.suggestions().filter(s => s.confidenceCategory === 'HIGH')
  );

  mediumConfidenceSuggestions = computed(() =>
    this.suggestions().filter(s => s.confidenceCategory === 'MEDIUM')
  );

  // Loading & Error State Signals for Clean UI UX
  loadingFeed = signal<boolean>(false);
  loadingPending = signal<boolean>(false);
  loadingSuggestions = signal<boolean>(false);
  loadingSuperchats = signal<boolean>(false);

  feedError = signal<string | null>(null);
  pendingError = signal<string | null>(null);

  postingQuestionKey = signal<string | null>(null);
  loadingAiDraftKey = signal<string | null>(null);

  private hasInitialLoaded = false;
  private pollSubscription?: Subscription;

  constructor() {
    this.startPolling();
  }

  startPolling() {
    if (this.pollSubscription) return;

    // Timer-based polling with exhaustMap to prevent overlapping requests
    this.pollSubscription = timer(0, 3000).pipe(
      filter(() => this.auth.isAuthenticated()),
      exhaustMap(() => this.pollCycle())
    ).subscribe();
  }

  stopPolling() {
    if (this.pollSubscription) {
      this.pollSubscription.unsubscribe();
      this.pollSubscription = undefined;
    }
  }

  private pollCycle() {
    return this.api.get<AssistantStatusDto>('/api/assistant/status').pipe(
      tap((st) => {
        if (st) {
          this.status.set(st);
        }
      }),
      exhaustMap((st) => {
        // Only poll live endpoints if assistant state is LIVE or live_chat_id is present
        if (st && (st.state === 'LIVE' || st.live_chat_id)) {
          if (!this.hasInitialLoaded) {
            this.loadingFeed.set(true);
            this.loadingPending.set(true);
            this.loadingSuggestions.set(true);
          }

          return forkJoin({
            pending: this.api.get<PendingQuestionsResponseDto>('/api/assistant/pending').pipe(catchError((err) => {
              this.pendingError.set('Failed to load pending questions');
              return of(null);
            })),
            feed: this.api.get<FeedResponseDto>('/api/assistant/feed').pipe(catchError((err) => {
              this.feedError.set('Failed to load chat feed');
              return of(null);
            })),
            suggestions: this.api.get<SuggestionsResponseDto>('/api/assistant/suggestions').pipe(catchError(() => of(null))),
            superchats: this.api.get<SuperchatsResponseDto>('/api/assistant/superchats').pipe(catchError(() => of(null)))
          }).pipe(
            tap((res) => {
              this.loadingFeed.set(false);
              this.loadingPending.set(false);
              this.loadingSuggestions.set(false);
              this.hasInitialLoaded = true;

              const pendingData = res.pending?.pending;
              if (pendingData) {
                this.pendingError.set(null);
                const mappedPending: { [key: string]: PendingQuestionVM } = {};
                Object.keys(pendingData).forEach(k => {
                  mappedPending[k] = mapPendingQuestion(pendingData[k]);
                });
                this.pendingQuestions.set(mappedPending);
              } else {
                this.pendingQuestions.set({});
              }

              if (res.feed?.recent_messages) {
                this.feedError.set(null);
                const mappedFeed = res.feed.recent_messages.map((m, idx) => mapFeedMessage(m, idx)).reverse();
                this.recentMessages.set(mappedFeed);
              } else {
                this.recentMessages.set([]);
              }

              if (res.suggestions?.suggestions) {
                const mappedSugg = res.suggestions.suggestions.map(s => mapSuggestion(s));
                this.suggestions.set(mappedSugg);
              } else {
                this.suggestions.set([]);
              }

              if (res.superchats?.superchats) {
                const mappedSc = res.superchats.superchats.map(sc => mapSuperchat(sc));
                this.superchats.set(mappedSc);
              } else {
                this.superchats.set([]);
              }
            })
          );
        } else {
          // Reset data signals when live stream is inactive
          this.loadingFeed.set(false);
          this.loadingPending.set(false);
          this.loadingSuggestions.set(false);
          this.pendingQuestions.set({});
          this.recentMessages.set([]);
          this.suggestions.set([]);
          this.superchats.set([]);
          return of(null);
        }
      }),
      catchError(() => {
        this.loadingFeed.set(false);
        this.loadingPending.set(false);
        this.loadingSuggestions.set(false);
        return of(null);
      })
    );
  }

  fetchStatus() {
    if (!this.auth.isAuthenticated()) return;
    this.api.get<AssistantStatusDto>('/api/assistant/status').pipe(
      tap((st) => {
        if (st) this.status.set(st);
      }),
      catchError(() => of(null))
    ).subscribe();
  }

  fetchPending() {
    if (!this.auth.isAuthenticated()) return;
    this.api.get<PendingQuestionsResponseDto>('/api/assistant/pending').pipe(
      tap((res) => {
        if (res && res.pending !== undefined) {
          const mappedPending: { [key: string]: PendingQuestionVM } = {};
          Object.keys(res.pending).forEach(k => {
            mappedPending[k] = mapPendingQuestion(res.pending[k]);
          });
          this.pendingQuestions.set(mappedPending);
        }
      }),
      catchError(() => of(null))
    ).subscribe();
  }

  dismissPending(questionKey: string) {
    if (!questionKey) return of(null);
    return this.api.delete<{ status: string }>(`/api/assistant/pending/${encodeURIComponent(questionKey)}`).pipe(
      tap(() => {
        const current = { ...this.pendingQuestions() };
        delete current[questionKey];
        this.pendingQuestions.set(current);
      }),
      catchError(() => of(null))
    );
  }

  resetDataState() {
    this.hasInitialLoaded = false;
    this.pendingQuestions.set({});
    this.recentMessages.set([]);
    this.suggestions.set([]);
    this.superchats.set([]);
    this.status.set({
      state: 'IDLE',
      auto_reply: false,
      ignored_names: [],
      ignored_ids: []
    });
  }

  connectStream(videoId: string) {
    if (!videoId || !videoId.trim()) {
      this.toast.error('Validation Error', 'Video ID or URL is required');
      return throwError(() => new Error('Video ID is required'));
    }
    // Wipe local state immediately on stream switch/connect
    this.resetDataState();

    return this.api.post<{ live_chat_id: string; video_title: string; channel_title: string }>('/api/assistant/connect_stream', { video_id: videoId.trim() }).pipe(
      tap((res) => {
        this.toast.success('Stream Connected', `Connected to "${res.video_title}"`);
        this.fetchStatus();
      }),
      catchError((err) => {
        const errorMsg = err.error?.detail || 'Failed to connect to video stream';
        this.toast.error('Connection Error', errorMsg);
        throw err;
      })
    );
  }

  startAssistant(videoId: string, liveChatId: string) {
    if (!videoId || !videoId.trim() || !liveChatId || !liveChatId.trim()) {
      this.toast.error('Validation Error', 'Video ID and Live Chat ID are required to start assistant');
      return throwError(() => new Error('Video ID and Live Chat ID are required'));
    }
    return this.api.post<{ status: string }>('/api/assistant/start', { video_id: videoId.trim(), live_chat_id: liveChatId.trim() }).pipe(
      tap(() => {
        this.toast.success('Assistant Started', 'Live chat poller is active 🟢');
        this.fetchStatus();
      }),
      catchError((err) => {
        const errorMsg = err.error?.detail || 'Failed to start assistant';
        this.toast.error('Start Error', errorMsg);
        throw err;
      })
    );
  }

  stopAssistant() {
    return this.api.post<{ status: string }>('/api/assistant/stop', {}).pipe(
      tap(() => {
        this.toast.info('Assistant Stopped', 'Poller is idle and data cleared ⏸️');
        this.resetDataState();
        this.fetchStatus();
      }),
      catchError((err) => {
        const errorMsg = err.error?.detail || 'Failed to stop assistant';
        this.toast.error('Stop Error', errorMsg);
        this.resetDataState();
        throw err;
      })
    );
  }

  updateSettings(settings: { auto_reply?: boolean; ignored_names?: string[]; ignored_ids?: string[] }) {
    return this.api.post<{ status: string }>('/api/assistant/settings', settings).pipe(
      tap(() => {
        this.toast.success('Settings Updated', 'Assistant controls updated successfully');
        this.fetchStatus();
      })
    );
  }

  generateAiDraft(question: string, questionKey: string) {
    if (!question || !question.trim() || !questionKey || !questionKey.trim()) {
      this.toast.error('Validation Error', 'Question text and question key are required');
      return throwError(() => new Error('Question text and key are required'));
    }
    this.loadingAiDraftKey.set(questionKey);
    return this.api.post<{ ok: boolean; reliable: boolean; answer: string; note: string }>('/api/ai/draft', { question: question.trim() }).pipe(
      tap((res) => {
        this.loadingAiDraftKey.set(null);
        if (res.ok && res.reliable && res.answer) {
          this.toast.success('AI Draft Generated', 'Grounded draft response created');
        } else if (res.note) {
          this.toast.warning('AI Notice', res.note);
        }
      }),
      catchError((err) => {
        this.loadingAiDraftKey.set(null);
        this.toast.error('AI Error', 'Failed to generate AI draft');
        throw err;
      })
    );
  }

  postAnswer(channelId: string, payload: PostRequestPayload) {
    if (!channelId || !channelId.trim()) {
      this.toast.error('Validation Error', 'Channel ID is required');
      return throwError(() => new Error('Channel ID is required'));
    }
    if (!payload.answer_text || !payload.answer_text.trim() || !payload.question_key || !payload.question_key.trim()) {
      this.toast.error('Validation Error', 'Answer text and question key are required');
      return throwError(() => new Error('Answer text and question key are required'));
    }

    if (payload.question_key) {
      this.postingQuestionKey.set(payload.question_key);
    }
    return this.api.post<PostResponsePayload>(`/api/channel/${channelId.trim()}/post`, payload).pipe(
      tap(() => {
        this.postingQuestionKey.set(null);
        this.toast.success('Response Posted! 🚀', 'Successfully posted answer to YouTube Live Chat');
        if (payload.question_key) {
          const current = { ...this.pendingQuestions() };
          delete current[payload.question_key];
          this.pendingQuestions.set(current);
        }
      }),
      catchError((err) => {
        this.postingQuestionKey.set(null);
        const errorMsg = err.error?.detail || 'Failed to post message to YouTube Live Chat';
        this.toast.error('Posting Failed', errorMsg);
        throw err;
      })
    );
  }

  dismissSuggestion(suggestionId: number | string) {
    return this.api.delete<{ status: string }>(`/api/assistant/suggestions/${suggestionId}`).pipe(
      tap(() => {
        const current = this.suggestions().filter(s => String(s.id) !== String(suggestionId));
        this.suggestions.set(current);
        this.toast.info('Suggestion Removed', 'Suggestion dismissed');
      }),
      catchError(() => {
        const current = this.suggestions().filter(s => String(s.id) !== String(suggestionId));
        this.suggestions.set(current);
        return of({ status: 'dismissed' });
      })
    );
  }

  ngOnDestroy() {
    this.stopPolling();
  }
}

