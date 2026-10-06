import { Component, inject, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { AssistantService } from '../../../core/services/assistant.service';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.css'
})
export class SidebarComponent {
  assistant = inject(AssistantService);

  pendingCount = computed(() => {
    return Object.keys(this.assistant.pendingQuestions()).length;
  });
}
