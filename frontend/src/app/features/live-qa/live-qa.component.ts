import { Component, inject, computed, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AuthService } from '../../core/services/auth.service';
import { AssistantService } from '../../core/services/assistant.service';
import { QaService } from '../../core/services/qa.service';
import { ToastService } from '../../core/services/toast.service';
import { PendingQuestionVM, SuggestionItemVM, FrequentQuestionAnalysisVM } from '../../core/models/assistant.models';
import { QaRecord, MatcherTestResult } from '../../core/models/qa.models';

function extractSmartKeywords(displayText: string, phrasings: string[] = []): string[] {
  const STOPWORDS = new Set([
    'what', 'whats', "what's", 'is', 'are', 'was', 'were', 'the', 'a', 'an', 'and', 'or', 'for',
    'in', 'on', 'at', 'to', 'from', 'with', 'your', 'you', 'u', 'ur', 'my', 'me', 'i', 'we',
    'do', 'does', 'did', 'can', 'could', 'would', 'will', 'should', 'how', 'why', 'when', 'where',
    'who', 'whom', 'which', 'tell', 'about', 'please', 'pls', 'bro', 'sir', 'dude', 'streamer',
    'hey', 'hi', 'hello', 'yo', 'have', 'got', 'has', 'any', 'some', 'much', 'many', 'like'
  ]);

  const candidates: string[] = [];

  // 1. Raw display text (exact phrasing from chat)
  if (displayText && displayText.trim()) {
    candidates.push(displayText.trim());
  }

  // 2. Original words > 2 chars joined (exact previous trigger formula)
  const origWords = displayText.toLowerCase().replace(/[^a-z0-9\s]/g, '').split(/\s+/).filter(w => w.length > 2);
  if (origWords.length > 0) {
    const joined = origWords.join(' ');
    if (!candidates.includes(joined)) {
      candidates.push(joined);
    }
  }

  // 3. Clean base and other phrasings
  const cleanBase = displayText.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
  if (cleanBase && !candidates.includes(cleanBase)) {
    candidates.push(cleanBase);
  }

  const allPhrases = [displayText, ...phrasings];
  for (const phrase of allPhrases) {
    const clean = phrase.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
    if (!clean) continue;

    const words = clean.split(' ').filter(w => w.length > 1 && !STOPWORDS.has(w));
    if (words.length > 0) {
      const entityPhrase = words.join(' ');
      if (entityPhrase && !candidates.includes(entityPhrase)) {
        candidates.push(entityPhrase);
      }
      words.forEach(w => {
        if (w.length >= 3 && !candidates.includes(w)) {
          candidates.push(w);
        }
      });
    }
  }

  return Array.from(new Set(candidates.filter(c => !!c && c.trim().length > 0))).slice(0, 6);
}

function findMatchingTrigger(
  displayText: string,
  keywords: string[],
  records: QaRecord[]
): { matched: boolean; trigger?: QaRecord } {
  const normQ = displayText.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
  for (const r of records) {
    const normRecord = (r.normalized_question || '').toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
    if (normRecord && (normQ === normRecord || normQ.includes(normRecord) || normRecord.includes(normQ))) {
      return { matched: true, trigger: r };
    }
    const examples = (r.original_question_examples || r.example_phrasings || []).map(e =>
      e.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim()
    );
    for (const kw of keywords) {
      const cleanKw = kw.toLowerCase().replace(/[^a-z0-9\s]/g, '').trim();
      if (cleanKw && examples.some(ex => ex === cleanKw || ex.includes(cleanKw) || cleanKw.includes(ex))) {
        return { matched: true, trigger: r };
      }
    }
  }
  return { matched: false };
}

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

  // Frequent Questions Analysis State
  pendingSortMode: 'recent' | 'frequency' = 'recent';
  frequentFilter: 'all' | 'unconfigured' | 'repeated' = 'all';
  showFrequentAnalysis = false;
  highlightedTriggerId: string | null = null;
  savingQuestionKey: string | null = null;

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
  showAutoResponderSection = false;
  showAutoResponderForm = false;
  editingTriggerId: string | null = null;
  triggerTitle = '';
  triggerKeywords = '';
  triggerAnswer = '';
  triggerAutoReply = true;
  triggerCooldown = 60;

  testInputText = '';
  testResult: MatcherTestResult | null = null;
  testingMatcher = false;

  // Frequent Questions Computed Analysis Signals
  totalChatQuestionsCount = computed(() => {
    const questions = this.assistant.pendingQuestions();
    return Object.values(questions).reduce((sum, q) => sum + (q.count || 1), 0);
  });

  allFrequentQuestions = computed<FrequentQuestionAnalysisVM[]>(() => {
    const questions = this.assistant.pendingQuestions();
    const records = this.qa.records();
    const list = Object.values(questions);
    const totalCount = this.totalChatQuestionsCount();

    const analyzed: FrequentQuestionAnalysisVM[] = list.map((entry) => {
      const askCount = entry.count || entry.examples?.length || 1;
      const uniqueViewers = Array.from(new Set(entry.occurrences.map(o => o.authorName).filter(Boolean)));
      const rawPhrasings = [entry.displayText, ...(entry.examples || []), ...entry.occurrences.map(o => o.text)];
      const phrasings = Array.from(new Set(rawPhrasings.filter(p => !!p && p.trim().length > 0)));
      const suggestedKeywords = extractSmartKeywords(entry.displayText, phrasings);
      const matchResult = findMatchingTrigger(entry.displayText, suggestedKeywords, records);
      const pct = totalCount > 0 ? Math.round((askCount / totalCount) * 100) : 0;

      return {
        rank: 0,
        questionKey: entry.questionKey,
        displayText: entry.displayText,
        count: askCount,
        percentage: pct,
        uniqueViewers,
        uniqueViewersCount: uniqueViewers.length || 1,
        phrasings: phrasings.slice(0, 4),
        suggestedKeywords,
        isInAutoResponder: matchResult.matched,
        matchedTriggerTitle: matchResult.trigger?.normalized_question,
        matchedTriggerId: matchResult.trigger?.id,
        pendingEntry: entry
      };
    });

    analyzed.sort((a, b) => {
      if (b.count !== a.count) {
        return b.count - a.count;
      }
      const timeA = a.pendingEntry.lastSeen || a.pendingEntry.occurrences?.[0]?.timestamp || '';
      const timeB = b.pendingEntry.lastSeen || b.pendingEntry.occurrences?.[0]?.timestamp || '';
      return timeB.localeCompare(timeA);
    });

    analyzed.forEach((item, idx) => {
      item.rank = idx + 1;
    });

    return analyzed;
  });

  frequentQuestions = computed(() => {
    const all = this.allFrequentQuestions();
    if (this.frequentFilter === 'unconfigured') {
      return all.filter(q => !q.isInAutoResponder);
    }
    if (this.frequentFilter === 'repeated') {
      return all.filter(q => q.count >= 2);
    }
    return all;
  });

  topFrequentQuestion = computed(() => {
    return this.allFrequentQuestions()[0] || null;
  });

  unconfiguredFrequentCount = computed(() => {
    return this.allFrequentQuestions().filter(q => !q.isInAutoResponder).length;
  });

  repeatedFrequentCount = computed(() => {
    return this.allFrequentQuestions().filter(q => q.count >= 2).length;
  });

  coveredTriggersCount = computed(() => {
    return this.allFrequentQuestions().filter(q => q.isInAutoResponder).length;
  });

  totalUniqueInquirers = computed(() => {
    const all = this.allFrequentQuestions();
    const viewers = new Set<string>();
    all.forEach(q => q.uniqueViewers.forEach(v => viewers.add(v)));
    return viewers.size;
  });

  pendingKeys = computed(() => {
    const questions = this.assistant.pendingQuestions();
    return Object.keys(questions).sort((a, b) => {
      if (this.pendingSortMode === 'frequency') {
        const countA = questions[a]?.count || 1;
        const countB = questions[b]?.count || 1;
        if (countB !== countA) {
          return countB - countA;
        }
      }
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
    if (this.savingQuestionKey === key) return;
    this.savingQuestionKey = key;

    const trimmedAnswer = (answer || '').trim();
    if (trimmedAnswer) {
      // Save pre-approved answer to memory bank (auto_reply=false by default)
      this.qa.saveMemory(question.trim(), trimmedAnswer, false).subscribe({
        next: () => {
          delete this.answerTexts[key];
          this.assistant.dismissPending(key).subscribe({
            next: () => {
              this.savingQuestionKey = null;
              this.toast.success('Saved to Q&A Memory', 'Answer saved to memory bank and removed from queue.');
            },
            error: () => {
              this.savingQuestionKey = null;
            }
          });
        },
        error: () => {
          this.savingQuestionKey = null;
        }
      });
    } else {
      delete this.answerTexts[key];
      this.assistant.dismissPending(key).subscribe({
        next: () => {
          this.savingQuestionKey = null;
          this.toast.success('Question Dismissed', 'Question removed from queue.');
        },
        error: () => {
          this.savingQuestionKey = null;
        }
      });
    }
  }

  onSaveAndPostNow(entry: PendingQuestionVM, key: string) {
    const answer = this.answerTexts[key];
    if (!answer || !answer.trim()) {
      this.toast.error('Validation Error', 'Answer text cannot be empty');
      return;
    }
    if (this.assistant.postingQuestionKey() === key || this.savingQuestionKey === key) {
      return;
    }
    this.savingQuestionKey = key;

    const channelId = this.auth.user()?.selected_channel_id || 'UC_DEMO_CHANNEL';
    const occId = this.selectedOccurrences[key] || (entry.occurrences?.[0]?.occurrenceId);
    const qKey = entry.questionKey || key;

    this.assistant.postAnswer(channelId, {
      answer_text: answer.trim(),
      question_key: qKey,
      occurrence_id: occId
    }).subscribe({
      next: () => {
        delete this.answerTexts[key];
        this.savingQuestionKey = null;
        this.assistant.fetchPending();
      },
      error: () => {
        this.savingQuestionKey = null;
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

  onAddFrequentToAutoResponder(item: FrequentQuestionAnalysisVM) {
    const answer = (this.answerTexts[item.questionKey] || '').trim();
    if (!answer) {
      this.toast.error(
        'Answer Required',
        'Please enter an answer text or click "Draft with AI" before adding to Auto-Responder'
      );
      return;
    }

    this.qa.saveMemory(
      item.displayText.trim(),
      answer,
      true, // auto_reply = true
      item.suggestedKeywords,
      60 // cooldown_seconds = 60
    ).subscribe({
      next: () => {
        this.toast.success(
          'Trigger Activated! 🤖',
          `Auto-Responder will now automatically reply to live chat when viewers ask "${item.displayText}"`
        );
      }
    });
  }

  onCustomizeTriggerFromFrequent(item: FrequentQuestionAnalysisVM) {
    this.editingTriggerId = null;
    this.triggerTitle = item.displayText;
    this.triggerKeywords = item.suggestedKeywords.join(', ');
    this.triggerAnswer = this.answerTexts[item.questionKey] || '';
    this.triggerAutoReply = true;
    this.triggerCooldown = 60;
    this.showAutoResponderSection = true;
    this.showAutoResponderForm = true;
    setTimeout(() => {
      const panel = document.getElementById('auto-responder-panel');
      if (panel) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 50);
  }

  onScrollToTrigger(triggerId: string) {
    this.showAutoResponderSection = true;
    this.highlightedTriggerId = triggerId;
    setTimeout(() => {
      const el = document.getElementById('trigger-' + triggerId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 50);
    setTimeout(() => {
      this.highlightedTriggerId = null;
    }, 3000);
  }

  onQuickAddTriggerFromPending(displayText: string, key: string) {
    const entry = this.assistant.pendingQuestions()[key];
    const phrasings = entry ? [displayText, ...(entry.examples || []), ...(entry.occurrences || []).map(o => o.text)] : [displayText];
    const keywords = extractSmartKeywords(displayText, phrasings);
    const answer = this.answerTexts[key] || '';
    this.editingTriggerId = null;
    this.triggerTitle = displayText;
    this.triggerAnswer = answer;
    this.triggerKeywords = keywords.join(', ');
    this.triggerAutoReply = true;
    this.triggerCooldown = 60;
    this.showAutoResponderSection = true;
    this.showAutoResponderForm = true;
    setTimeout(() => {
      const panel = document.getElementById('auto-responder-panel');
      if (panel) {
        panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 50);
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

    const cooldownVal = this.triggerCooldown !== undefined && this.triggerCooldown !== null ? Math.max(0, Number(this.triggerCooldown)) : 60;

    this.qa.saveMemory(
      this.triggerTitle.trim(),
      this.triggerAnswer.trim(),
      this.triggerAutoReply,
      kwList,
      cooldownVal
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
    this.triggerCooldown = record.cooldown_seconds !== undefined && record.cooldown_seconds !== null ? record.cooldown_seconds : 60;
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
    this.triggerCooldown = 60;
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
