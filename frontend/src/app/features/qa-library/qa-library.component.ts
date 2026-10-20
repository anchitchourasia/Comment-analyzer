import { Component, inject, HostListener } from '@angular/core';
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
  savingRecord = false;
  private openerElement: HTMLElement | null = null;

  newQuestion = '';
  newAnswer = '';
  newAutoReply = false;

  testQuestionInput = '';
  testResult: MatcherTestResult | null = null;
  testing = false;

  @HostListener('document:keydown.escape')
  onEscapePress() {
    if (this.showAddModal) {
      this.closeModal();
    }
  }

  filteredRecords() {
    const q = this.searchQuery.toLowerCase().trim();
    if (!q) return this.qaService.records();
    return this.qaService.records().filter(r => 
      r.normalized_question.toLowerCase().includes(q) ||
      r.answer_text.toLowerCase().includes(q)
    );
  }

  openAddModal() {
    this.openerElement = document.activeElement as HTMLElement;
    this.showAddModal = true;
    setTimeout(() => {
      const input = document.getElementById('newQuestionInput') as HTMLInputElement;
      if (input) {
        input.focus();
      }
    }, 50);
  }

  closeModal(force = false) {
    if (!force && (this.newQuestion.trim() || this.newAnswer.trim())) {
      if (!confirm('Discard unsaved changes?')) {
        return;
      }
    }
    this.showAddModal = false;
    this.newQuestion = '';
    this.newAnswer = '';
    this.newAutoReply = false;
    this.savingRecord = false;

    if (this.openerElement) {
      this.openerElement.focus();
      this.openerElement = null;
    }
  }

  onBackdropClick() {
    this.closeModal();
  }

  onSaveNewRecord() {
    if (this.savingRecord || !this.newQuestion.trim() || !this.newAnswer.trim()) return;
    this.savingRecord = true;
    this.qaService.saveMemory(this.newQuestion.trim(), this.newAnswer.trim(), this.newAutoReply).subscribe({
      next: () => {
        this.savingRecord = false;
        this.closeModal(true);
        this.toast.success('Record Added', 'New pre-approved Q&A pair saved in memory bank.');
      },
      error: () => {
        this.savingRecord = false;
      }
    });
  }

  onDeleteRecord(id: string) {
    if (confirm('Are you sure you want to delete this pre-approved Q&A record?')) {
      this.qaService.deleteMemory(id).subscribe({
        next: () => {
          this.toast.success('Record Deleted', 'Q&A record deleted from memory bank.');
        }
      });
    }
  }

  onRunSandboxTest() {
    if (!this.testQuestionInput.trim()) return;
    this.testing = true;
    this.qaService.testMatcher(this.testQuestionInput.trim()).subscribe({
      next: (res) => {
        this.testing = false;
        this.testResult = res;
      },
      error: () => {
        this.testing = false;
      }
    });
  }
}
