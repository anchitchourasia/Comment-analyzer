import { Component, inject, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { AssistantService } from '../../core/services/assistant.service';
import { QaService } from '../../core/services/qa.service';
import { ToastService } from '../../core/services/toast.service';
import { PendingQuestionVM, SuggestionItemVM } from '../../core/models/assistant.models';
import { QaRecord, MatcherTestResult } from '../../core/models/qa.models';

@Component({
  selector: 'app-live-qa',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './live-qa.component.html',
  styleUrl: './live-qa.component.css'
})
export class LiveQaComponent {
  auth = inject(AuthService);
  assistant = inject(AssistantService);
  qa = inject(QaService);
  toast = inject(ToastService);

  answerTexts: { [key: string]: string } = {};
  selectedOccurrences: { [key: string]: string } = {};
  suggestionAnswerTexts: { [key: string | number]: string } = {};
  editingSuggestions: { [key: string | number]: boolean } = {};
  autoSendTriggered: { [key: string | number]: boolean } = {};

  constructor() {
    effect(() => {
      const highConf = this.assistant.highConfidenceSuggestions();
      highConf.forEach((sugg) => {
        if ((sugg.autoReply || sugg.isKeywordTrigger) && !this.autoSendTriggered[sugg.id]) {
          this.autoSendTriggered[sugg.id] = true;
          this.onPostSuggestion(sugg);
        }
      });
    });
  }

  // Auto-Responder Keyword System State
  showAutoResponderForm = false;
  editingTriggerId: string | null = null;
  triggerTitle = '';
  triggerKeywords = '';
  triggerAnswer = '';
  triggerAutoReply = true;

  testInputText = '';
  testResult: MatcherTestResult | null = null;
  testingMatcher = false;

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

  // --- Auto-Responder Keyword System Methods (100% Real-Time Dynamic) ---

  onQuickAddTriggerFromPending(displayText: string, key: string) {
    const answer = this.answerTexts[key] || '';
    this.editingTriggerId = null;
    this.triggerTitle = displayText;
    this.triggerAnswer = answer;
    // Derive initial keywords dynamically from real-time question phrasing
    const words = displayText.toLowerCase().replace(/[^a-z0-9\s]/g, '').split(/\s+/).filter(w => w.length > 2);
    this.triggerKeywords = [displayText, words.join(' ')].filter((v, i, a) => v && a.indexOf(v) === i).join(', ');
    this.triggerAutoReply = true;
    this.showAutoResponderForm = true;
  }

  onSaveCustomKeywordTrigger() {
    if (!this.triggerTitle || !this.triggerTitle.trim()) {
      this.toast.error('Validation Error', 'Trigger title/question is required');
      return;
    }
    if (!this.triggerAnswer || !this.triggerAnswer.trim()) {
      this.toast.error('Validation Error', 'Response answer text is required');
      return;
    }
    const kwList = this.triggerKeywords
      .split(',')
      .map(k => k.trim())
      .filter(k => k.length > 0);

    this.qa.saveMemory(
      this.triggerTitle.trim(),
      this.triggerAnswer.trim(),
      this.triggerAutoReply,
      kwList
    ).subscribe({
      next: () => {
        this.resetTriggerForm();
      }
    });
  }

  onEditTrigger(record: QaRecord) {
    this.editingTriggerId = record.id;
    this.triggerTitle = record.normalized_question || '';
    this.triggerAnswer = record.answer_text || '';
    this.triggerKeywords = (record.original_question_examples || record.example_phrasings || []).join(', ');
    this.triggerAutoReply = record.auto_reply !== false;
    this.showAutoResponderForm = true;
  }

  onDeleteTrigger(recordId: string) {
    if (confirm('Are you sure you want to delete this auto-responder keyword trigger?')) {
      this.qa.deleteMemory(recordId).subscribe();
    }
  }

  resetTriggerForm() {
    this.editingTriggerId = null;
    this.triggerTitle = '';
    this.triggerKeywords = '';
    this.triggerAnswer = '';
    this.triggerAutoReply = true;
    this.showAutoResponderForm = false;
  }

  onTestKeywordDetection() {
    if (!this.testInputText || !this.testInputText.trim()) {
      this.toast.error('Validation Error', 'Enter sample chat message to test detection');
      return;
    }
    this.testingMatcher = true;
    this.qa.testMatcher(this.testInputText.trim()).subscribe({
      next: (res) => {
        this.testingMatcher = false;
        this.testResult = res;
      },
      error: () => {
        this.testingMatcher = false;
      }
    });
  }
}
