// --- Raw Backend DTO Interfaces (FastAPI JSON Responses) ---

export interface FeedMessageDto {
  author?: string | null;
  text?: string | null;
  sentiment?: number | null;
  at?: string | null;
  kind?: string | null;
  display_string?: string | null;
}

export interface FeedResponseDto {
  recent_messages: FeedMessageDto[];
}

export interface QuestionOccurrenceDto {
  occurrence_id: string;
  message_id?: string | null;
  live_chat_id?: string | null;
  video_id?: string | null;
  channel_id?: string | null;
  author_name?: string | null;
  text?: string | null;
  raw_text?: string | null;
  timestamp?: string | null;
}

export interface PendingQuestionEntryDto {
  key?: string;
  question_key?: string;
  examples: string[];
  count: number;
  occurrences: QuestionOccurrenceDto[];
  status?: 'pending' | 'in_flight' | 'posted' | 'failed' | 'outcome_unknown' | string;
  error?: string | null;
  in_flight_at?: string | null;
  posted_message_id?: string | null;
}

export interface PendingQuestionsResponseDto {
  pending: { [key: string]: PendingQuestionEntryDto };
}

export interface SuggestionItemDto {
  id: number | string;
  question?: string | null;
  answer?: string | null;
  score: number;
  author?: string | null;
  record_id?: string | null;
  live_chat_id?: string | null;
  message_id?: string | null;
  auto_reply?: boolean;
  is_keyword_trigger?: boolean;
}

export interface SuggestionsResponseDto {
  suggestions: SuggestionItemDto[];
}

export interface SuperchatAlertDto {
  id: string;
  author?: string | null;
  channel_id?: string | null;
  text?: string | null;
  amount?: string | null;
  at?: string | null;
}

export interface SuperchatsResponseDto {
  superchats: SuperchatAlertDto[];
}

export interface AssistantStatusDto {
  state: 'LIVE' | 'IDLE' | string;
  live_chat_id?: string | null;
  video_id?: string | null;
  video_title?: string | null;
  channel_title?: string | null;
  auto_reply: boolean;
  ignored_names: string[];
  ignored_ids: string[];
}

export interface PostRequestPayload {
  answer_text: string;
  question_key?: string;
  occurrence_id?: string;
  live_chat_id?: string;
  auto_reply_opt_in?: boolean;
  record_id?: string;
}

export interface PostResponsePayload {
  status: string;
  message: string;
  youtube_message_id?: string;
  live_chat_id?: string;
  error_reason?: string;
}


// --- Clean Angular View Models for UI Rendering ---

export interface ChatFeedItemVM {
  id: string;
  authorName: string;
  messageText: string;
  sentimentScore: number;
  sentimentLabel: 'positive' | 'negative' | 'neutral';
  timestamp?: string;
  kind: 'chat' | 'superchat';
  displayString?: string;
}

export interface QuestionOccurrenceVM {
  occurrenceId: string;
  messageId: string;
  authorName: string;
  text: string;
  timestamp: string;
}

export interface PendingQuestionVM {
  questionKey: string;
  displayText: string;
  examples: string[];
  count: number;
  status: 'pending' | 'in_flight' | 'posted' | 'failed' | 'outcome_unknown';
  error?: string;
  lastSeen?: string;
  occurrences: QuestionOccurrenceVM[];
}

export interface SuggestionItemVM {
  id: string | number;
  questionText: string;
  answerText: string;
  score: number; // 0.0 to 1.0
  scorePercentage: number; // 0 to 100
  authorName: string;
  confidenceCategory: 'HIGH' | 'MEDIUM';
  recordId?: string;
  liveChatId?: string;
  messageId?: string;
  autoReply?: boolean;
  isKeywordTrigger?: boolean;
}

export interface SuperchatAlertVM {
  id: string;
  authorName: string;
  amountText: string;
  messageText: string;
  timestamp?: string;
}

export type AssistantStatusVM = AssistantStatusDto;


// --- Explicit Mapping Layer Functions ---

export function mapFeedMessage(dto: FeedMessageDto, index: number): ChatFeedItemVM {
  const sentimentScore = typeof dto.sentiment === 'number' ? dto.sentiment : 0;
  let label: 'positive' | 'negative' | 'neutral' = 'neutral';
  if (sentimentScore >= 0.05) label = 'positive';
  else if (sentimentScore <= -0.05) label = 'negative';

  return {
    id: `msg_${index}_${dto.at || Date.now()}`,
    authorName: dto.author?.trim() || 'Unknown viewer',
    messageText: dto.text?.trim() || 'Message unavailable',
    sentimentScore,
    sentimentLabel: label,
    timestamp: dto.at || undefined,
    kind: dto.kind === 'superchat' ? 'superchat' : 'chat',
    displayString: dto.display_string || undefined
  };
}

export function mapPendingQuestion(dto: PendingQuestionEntryDto): PendingQuestionVM {
  const ex = dto.examples && dto.examples.length > 0 ? dto.examples : [dto.question_key || dto.key || 'Question unavailable'];
  const occs: QuestionOccurrenceVM[] = (dto.occurrences || []).map(o => ({
    occurrenceId: o.occurrence_id,
    messageId: o.message_id || '',
    authorName: o.author_name?.trim() || 'viewer',
    text: o.text || o.raw_text || ex[0],
    timestamp: o.timestamp || ''
  }));

  const rawLastSeen = (dto as any).last_seen || (occs[0]?.timestamp) || '';

  return {
    questionKey: dto.question_key || dto.key || ex[0],
    displayText: ex[0],
    examples: ex,
    count: dto.count || ex.length || 1,
    status: (dto.status as any) || 'pending',
    error: dto.error || undefined,
    lastSeen: rawLastSeen,
    occurrences: occs
  };
}

export function mapSuggestion(dto: SuggestionItemDto): SuggestionItemVM {
  const score = typeof dto.score === 'number' ? dto.score : 0.5;
  const scorePct = Math.round(score * 100);
  const category: 'HIGH' | 'MEDIUM' = score >= 0.8 ? 'HIGH' : 'MEDIUM';

  return {
    id: dto.id,
    questionText: dto.question?.trim() || 'Question unavailable',
    answerText: dto.answer?.trim() || 'Suggested answer unavailable',
    score,
    scorePercentage: scorePct,
    authorName: dto.author?.trim() || 'Viewer',
    confidenceCategory: category,
    recordId: dto.record_id || undefined,
    liveChatId: dto.live_chat_id || undefined,
    messageId: dto.message_id || undefined,
    autoReply: dto.auto_reply !== undefined ? dto.auto_reply : (score >= 0.8),
    isKeywordTrigger: dto.is_keyword_trigger !== undefined ? dto.is_keyword_trigger : (score >= 0.8)
  };
}

export function mapSuperchat(dto: SuperchatAlertDto): SuperchatAlertVM {
  return {
    id: dto.id,
    authorName: dto.author?.trim() || 'Anonymous Superchat',
    amountText: dto.amount?.trim() || 'Super Chat',
    messageText: dto.text?.trim() || '',
    timestamp: dto.at || undefined
  };
}
