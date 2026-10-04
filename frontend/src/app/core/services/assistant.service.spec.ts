import { TestBed } from '@angular/core/testing';
import { AssistantService } from './assistant.service';
import { ApiClientService } from './api-client.service';
import { AuthService } from './auth.service';
import { ToastService } from './toast.service';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';

describe('AssistantService', () => {
  let service: AssistantService;
  let apiMock: jasmine.SpyObj<ApiClientService>;
  let authMock: any;
  let toastMock: jasmine.SpyObj<ToastService>;

  beforeEach(() => {
    apiMock = jasmine.createSpyObj('ApiClientService', ['get', 'post', 'delete']);
    toastMock = jasmine.createSpyObj('ToastService', ['success', 'error', 'info', 'warning']);
    
    authMock = {
      isAuthenticated: () => true,
      hasChannelSelected: () => true,
      user: () => ({ user_id: 'u123', selected_channel_id: 'UC_TEST' })
    };

    apiMock.get.and.returnValue(of({
      state: 'IDLE',
      auto_reply: false,
      ignored_names: [],
      ignored_ids: []
    }));

    TestBed.configureTestingModule({
      providers: [
        AssistantService,
        { provide: ApiClientService, useValue: apiMock },
        { provide: AuthService, useValue: authMock },
        { provide: ToastService, useValue: toastMock }
      ]
    });

    service = TestBed.inject(AssistantService);
  });

  afterEach(() => {
    service.ngOnDestroy();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should not poll assistant live endpoints if user is unauthenticated', () => {
    authMock.isAuthenticated = () => false;
    service.fetchStatus();
    expect(apiMock.get).not.toHaveBeenCalledWith('/api/assistant/pending');
  });

  it('should validate inputs for connectStream and reject empty strings', (done) => {
    service.connectStream('').subscribe({
      error: (err) => {
        expect(err.message).toBe('Video ID is required');
        expect(toastMock.error).toHaveBeenCalled();
        done();
      }
    });
  });

  it('should validate inputs for startAssistant and reject empty strings', (done) => {
    service.startAssistant('', '').subscribe({
      error: (err) => {
        expect(err.message).toBe('Video ID and Live Chat ID are required');
        expect(toastMock.error).toHaveBeenCalled();
        done();
      }
    });
  });

  it('should validate inputs for postAnswer and reject empty channel ID or answer text', (done) => {
    service.postAnswer('', { answer_text: '', question_key: '' }).subscribe({
      error: (err) => {
        expect(err.message).toBe('Channel ID is required');
        expect(toastMock.error).toHaveBeenCalled();
        done();
      }
    });
  });

  it('should reset data signals when stopping assistant', () => {
    apiMock.post.and.returnValue(of({ status: 'stopped' }));
    service.stopAssistant().subscribe(() => {
      expect(service.pendingQuestions()).toEqual({});
      expect(service.recentMessages()).toEqual([]);
      expect(service.suggestions()).toEqual([]);
      expect(service.superchats()).toEqual([]);
    });
  });

  it('should handle API 422 gracefully without infinite retry loop', () => {
    const error422 = new HttpErrorResponse({ status: 422, statusText: 'Unprocessable Entity' });
    apiMock.get.and.returnValue(throwError(() => error422));

    service.fetchStatus();
    expect(apiMock.get).toHaveBeenCalledWith('/api/assistant/status');
  });

  it('should correctly map raw DTOs to UI View Models', () => {
    const rawFeed = { author: 'Alice', text: 'Hello stream!', sentiment: 0.8, at: '2026-10-04T00:00:00Z', kind: 'chat' };
    const mappedFeed = service.mapFeedMessage(rawFeed, 0);
    expect(mappedFeed.authorName).toBe('Alice');
    expect(mappedFeed.messageText).toBe('Hello stream!');
    expect(mappedFeed.sentimentLabel).toBe('positive');

    const rawSuggestion = { id: 1, question: 'What software is this?', answer: 'It is Antigravity.', score: 0.87, author: 'Bob' };
    const mappedSuggestion = service.mapSuggestion(rawSuggestion);
    expect(mappedSuggestion.questionText).toBe('What software is this?');
    expect(mappedSuggestion.answerText).toBe('It is Antigravity.');
    expect(mappedSuggestion.scorePercentage).toBe(87);
    expect(mappedSuggestion.confidenceCategory).toBe('HIGH');
  });

  it('should categorize suggestions into high (>=80%) and medium (50%-79%) confidence signals', () => {
    const rawHigh = { id: 1, question: 'Q1', answer: 'A1', score: 0.85, author: 'User1' };
    const rawMed = { id: 2, question: 'Q2', answer: 'A2', score: 0.65, author: 'User2' };

    apiMock.get.and.callFake((url: string) => {
      if (url === '/api/assistant/suggestions') {
        return of({ suggestions: [rawHigh, rawMed] });
      }
      return of({});
    });

    service.fetchSuggestions();
    expect(service.highConfidenceSuggestions().length).toBe(1);
    expect(service.highConfidenceSuggestions()[0].scorePercentage).toBe(85);
    expect(service.mediumConfidenceSuggestions().length).toBe(1);
    expect(service.mediumConfidenceSuggestions()[0].scorePercentage).toBe(65);
  });
});
