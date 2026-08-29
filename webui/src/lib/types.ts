export type ContentPieceStatus =
  | "draft"
  | "generating"
  | "pending_approval"
  | "approved"
  | "rejected"
  | "posted"
  | "failed";

export interface Campaign {
  id: number;
  client_id: number;
  name: string;
  horizon_days: number;
  status: string;
  created_at: string;
}

export interface ContentPieceSummary {
  id: number;
  campaign_id: number;
  type: "video" | "image" | "audio";
  status: ContentPieceStatus;
  generation_prompt: string | null;
  scheduled_for: string | null;
  posted_at: string | null;
  created_at: string;
}
