export interface QaRecord {
  id: string;
  normalized_question: string;
  answer_text: string;
  example_phrasings?: string[];
  original_question_examples?: string[];
  auto_reply: boolean;
  cooldown_seconds?: number;
  created_at?: string;
  usage_count?: number;
}

export interface CandidateMatch {
  record: QaRecord;
  ranking_score?: number;
  score?: number;
  semantic_score?: number | null;
  lexical_score?: number | null;
  match_type: string;
}

export interface MatcherTestResult {
  question: string;
  matched_record?: QaRecord | null;
  score: number;
  match_type?: string;
  retrieval_source?: string;
  semantic_score?: number | null;
  lexical_score?: number | null;
  ranking_score?: number;
  model_name?: string;
  status?: string;
  fallback_reason?: string;
  top_candidates?: CandidateMatch[];
  ai_draft?: string;
  ai_note?: string;
}

export interface AiDraftResult {
  ok: boolean;
  reliable: boolean;
  answer: string;
  note: string;
}

/** Shape returned by GET /api/pinecone/status */
export interface PineconeStatus {
  available: boolean;
  index_name?: string;
  namespace?: string;
  vector_count?: number | string;
  dimension?: number;
  error?: string;
}
