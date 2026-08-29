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

export interface PieceAsset {
  type: "image" | "audio" | "video" | "thumbnail" | "subtitle";
  signed_url: string;
  mime_type: string | null;
  width: number | null;
  height: number | null;
  duration: number | null;
}

export interface Publication {
  id: number;
  social_account_id: number;
  platform: string;
  status: "queued" | "running" | "retrying" | "succeeded" | "failed";
  platform_post_url: string | null;
  error_message: string | null;
}

export interface PieceDetail extends ContentPieceSummary {
  avatar_id: number | null;
  is_synthetic_media: boolean;
  content_category: string | null;
  risk_level: string;
  requires_human_review: boolean;
  assets: PieceAsset[];
  publications: Publication[];
}
