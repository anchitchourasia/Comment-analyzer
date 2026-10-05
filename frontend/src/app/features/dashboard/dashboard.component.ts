import { Component, inject, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/services/auth.service';
import { AssistantService } from '../../core/services/assistant.service';
import { QaService } from '../../core/services/qa.service';
import { ToastService } from '../../core/services/toast.service';
import { PendingQuestionVM, SuggestionItemVM } from '../../core/models/assistant.models';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.css'
})
export class DashboardComponent {
  auth = inject(AuthService);
  assistant = inject(AssistantService);
  qa = inject(QaService);
  toast = inject(ToastService);

  videoInput = '';
  connecting = false;
  starting = false;
  stopping = false;

  activeVideoTitle = '';
  activeChannelTitle = '';
  activeLiveChatId = '';

  answerTexts: { [key: string]: string } = {};
  selectedOccurrences: { [key: string]: string } = {};
  suggestionAnswerTexts: { [key: string | number]: string } = {};
  editingSuggestions: { [key: string | number]: boolean } = {};

  pendingKeys = computed(() => {
    const questions = this.assistant.pendingQuestions();
    return Object.keys(questions).sort((a, b) => {
      const timeA = questions[a]?.lastSeen || questions[a]?.occurrences?.[0]?.timestamp || '';
      const timeB = questions[b]?.lastSeen || questions[b]?.occurrences?.[0]?.timestamp || '';
      if (timeA && timeB) {
        return timeB.localeCompare(timeA);
      }
      return 0;
    });
  });

  onConnectStream() {
    if (!this.videoInput) return;
    this.connecting = true;
    this.answerTexts = {};
    this.selectedOccurrences = {};
    this.assistant.resetDataState();

    this.assistant.connectStream(this.videoInput).subscribe({
      next: (res) => {
        this.connecting = false;
        this.activeVideoTitle = res.video_title;
        this.activeChannelTitle = res.channel_title;
        this.activeLiveChatId = res.live_chat_id;
      },
      error: () => this.connecting = false
    });
  }

  onStartAssistant() {
    if (!this.activeLiveChatId) return;
    this.starting = true;
    this.assistant.startAssistant(this.videoInput, this.activeLiveChatId).subscribe({
      next: () => this.starting = false,
      error: () => this.starting = false
    });
  }

  onStopAssistant() {
    this.stopping = true;
    this.assistant.stopAssistant().subscribe({
      next: () => {
        this.stopping = false;
        this.activeVideoTitle = '';
        this.activeChannelTitle = '';
        this.activeLiveChatId = '';
        this.videoInput = '';
        this.answerTexts = {};
        this.selectedOccurrences = {};
      },
      error: () => {
        this.stopping = false;
        this.activeVideoTitle = '';
        this.activeChannelTitle = '';
        this.activeLiveChatId = '';
        this.videoInput = '';
        this.answerTexts = {};
        this.selectedOccurrences = {};
      }
    });
  }

  onGetAiDraft(question: string, key: string) {
    this.assistant.generateAiDraft(question, key).subscribe({
      next: (res) => {
        if (res.answer) {
          this.answerTexts[key] = res.answer;
        }
      }
    });
  }

  onSaveApproveOnly(question: string, answer: string, key: string) {
    if (!answer) {
      this.toast.error('Validation Error', 'Answer text cannot be empty');
      return;
    }
    this.qa.saveMemory(question, answer).subscribe({
      next: () => {
        delete this.answerTexts[key];
        this.assistant.dismissPending(key).subscribe();
      }
    });
  }

  onSaveAndPostNow(entry: PendingQuestionVM, key: string) {
    const answer = this.answerTexts[key];
    if (!answer) {
      this.toast.error('Validation Error', 'Answer text cannot be empty');
      return;
    }
    const channelId = this.auth.user()?.selected_channel_id || 'UC_DEMO_CHANNEL';
    const occId = this.selectedOccurrences[key] || (entry.occurrences?.[0]?.occurrenceId);
    const qKey = entry.questionKey || key;

    this.assistant.postAnswer(channelId, {
      answer_text: answer,
      question_key: qKey,
      occurrence_id: occId
    }).subscribe({
      next: () => {
        delete this.answerTexts[key];
        this.assistant.fetchPending();
      },
      error: () => {
        this.assistant.fetchPending();
      }
    });
  }

  getSuggestionAnswer(sugg: SuggestionItemVM): string {
    if (this.suggestionAnswerTexts[sugg.id] !== undefined) {
      return this.suggestionAnswerTexts[sugg.id];
    }
    return sugg.answerText || '';
  }

  toggleEditSuggestion(sugg: SuggestionItemVM) {
    const currentEdit = !!this.editingSuggestions[sugg.id];
    if (!currentEdit && this.suggestionAnswerTexts[sugg.id] === undefined) {
      this.suggestionAnswerTexts[sugg.id] = sugg.answerText || '';
    }
    this.editingSuggestions[sugg.id] = !currentEdit;
  }

  onSuggestionAnswerChange(suggId: string | number, text: string) {
    this.suggestionAnswerTexts[suggId] = text;
  }

  onDismissSuggestion(sugg: SuggestionItemVM) {
    this.assistant.dismissSuggestion(sugg.id).subscribe({
      next: () => {
        delete this.suggestionAnswerTexts[sugg.id];
        delete this.editingSuggestions[sugg.id];
      }
    });
  }

  onPostSuggestion(sugg: SuggestionItemVM) {
    const channelId = this.auth.user()?.selected_channel_id || 'UC_DEMO_CHANNEL';
    const qKey = (sugg.recordId || sugg.questionText);
    const answerToPost = this.getSuggestionAnswer(sugg);

    if (!answerToPost || !answerToPost.trim()) {
      this.toast.error('Validation Error', 'Answer text cannot be empty');
      return;
    }

    this.assistant.postAnswer(channelId, {
      answer_text: answerToPost.trim(),
      question_key: qKey,
      occurrence_id: sugg.id ? sugg.id.toString() : undefined
    }).subscribe({
      next: () => {
        delete this.suggestionAnswerTexts[sugg.id];
        delete this.editingSuggestions[sugg.id];
        this.assistant.dismissSuggestion(sugg.id).subscribe();
      }
    });
  }
}

