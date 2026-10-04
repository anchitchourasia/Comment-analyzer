export interface ChannelInfo {
  id: string;
  title: string;
  handle?: string;
}

export interface UserSession {
  user_id: string;
  account_label: string;
  user_email?: string;
  user_name?: string;
  selected_channel_id?: string;
  selected_channel_title?: string;
  selected_channel_handle?: string;
  channel_connection_status: 'unconnected' | 'connected' | 'missing_scope' | 'missing_write_scope' | 'no_channels' | 'api_error' | string;
  has_write_scope: boolean;
  granted_scopes?: string;
  verified_channels: string[];
  channel_titles: { [id: string]: string };
}

export interface LoginInitResponse {
  auth_url: string;
  state: string;
}

export interface OAuthInitResponse {
  auth_url: string;
  state: string;
}

export interface OAuthCallbackResponse {
  status: string;
  channels: ChannelInfo[];
}

export interface ChannelSelectResponse {
  status: string;
  channel_id: string;
  channel_title: string;
}
