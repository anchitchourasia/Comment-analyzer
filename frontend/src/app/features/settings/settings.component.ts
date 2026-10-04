import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../core/services/auth.service';
import { AssistantService } from '../../core/services/assistant.service';
import { ToastService } from '../../core/services/toast.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './settings.component.html',
  styleUrl: './settings.component.css'
})
export class SettingsComponent {
  auth = inject(AuthService);
  assistant = inject(AssistantService);
  toast = inject(ToastService);

  ignoredNamesInput = '';
  ignoredIdsInput = '';

  constructor() {
    const st = this.assistant.status();
    this.ignoredNamesInput = (st.ignored_names || []).join(', ');
    this.ignoredIdsInput = (st.ignored_ids || []).join(', ');
  }

  onSaveFilters() {
    const names = this.ignoredNamesInput.split(',').map(n => n.trim()).filter(Boolean);
    const ids = this.ignoredIdsInput.split(',').map(i => i.trim()).filter(Boolean);

    this.assistant.updateSettings({
      ignored_names: names,
      ignored_ids: ids
    }).subscribe({
      next: () => this.toast.success('Filters Updated', 'Bot filter rules updated')
    });
  }

  onDisconnectChannel() {
    if (confirm('Disconnect YouTube channel? Encryption tokens will be permanently deleted.')) {
      this.auth.disconnectChannel().subscribe();
    }
  }
}
