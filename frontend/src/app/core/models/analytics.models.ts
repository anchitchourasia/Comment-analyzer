export interface CommentItem {
  author: string;
  text: string;
  score: number;
}

export interface CommentAnalytics {
  video_id: string;
  total_comments: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  positive_comments: CommentItem[];
  negative_comments: CommentItem[];
}
