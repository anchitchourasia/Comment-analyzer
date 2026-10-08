import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { QaService } from '../../core/services/qa.service';
import { ToastService } from '../../core/services/toast.service';
import { MatcherTestResult } from '../../core/models/qa.models';

@Component({
  selector: 'app-qa-library',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './qa-library.component.html',
  styleUrl: './qa-library.component.css'
})
export class QaLibraryComponent {
  qaService = inject(QaService);
  toast = inject(ToastService);

  searchQuery = '';
  showAddModal = false;

  newQuestion = '';
  newAnswer = '';
  newAutoReply = false;

  testQuestionInput = '';
  testResult: MatcherTestResult | null = null;
  testing = false;

  filteredRecords() {
    const q = this.searchQuery.toLowerCase().trim();
    if (!q) return this.qaService.records();
    return this.qaService.records().filter(r => 
      r.normalized_question.toLowerCase().includes(q) ||
      r.answer_text.toLowerCase().includes(q)
    );
  }

  onSaveNewRecord() {
    if (!this.newQuestion || !this.newAnswer) return;
    this.qaService.saveMemory(this.newQuestion, this.newAnswer, this.newAutoReply).subscribe({
      next: () => {
        this.showAddModal = false;
        this.newQuestion = '';
        this.newAnswer = '';
        this.newAutoReply = false;
      }
    });
  }

  onDeleteRecord(id: string) {
    if (confirm('Are you sure you want to delete this pre-approved Q&A record?')) {
      this.qaService.deleteMemory(id).subscribe();
    }
  }

  onRunSandboxTest() {
    if (!this.testQuestionInput) return;
    this.testing = true;
    this.qaService.testMatcher(this.testQuestionInput).subscribe({
      next: (res) => {
        this.testing = false;
        this.testResult = res;
      },
      error: () => this.testing = false
    });
  }
}
