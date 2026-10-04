import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AnalyticsService } from '../../core/services/analytics.service';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.css'
})
export class AnalyticsComponent {
  analyticsService = inject(AnalyticsService);
  videoIdInput = '';

  onAnalyze() {
    if (!this.videoIdInput) return;
    this.analyticsService.analyzeVideo(this.videoIdInput).subscribe();
  }
}
