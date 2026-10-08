export interface QaRecord {
  id: string;
  normalized_question: string;
  answer_text: string;
  example_phrasings?: string[];
  original_question_examples?: string[];
  auto_reply: boolean;
  created_at?: string;
  usage_count?: number;
}

export interface MatcherTestResult {
  question: string;
  matched_record?: QaRecord | null;
  score: number;
  ai_draft?: string;
  ai_note?: string;
}

export interface AiDraftResult {
  ok: boolean;
  reliable: boolean;
  answer: string;
  note: string;
}
