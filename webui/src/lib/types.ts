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
  narration_script: string | null;
  scheduled_for: string | null;
  posted_at: string | null;
  created_at: string;
}

/** Lives here, next to the union it labels, so the queue and the detail
 * screen cannot drift into calling the same value different things. */
export const PIECE_TYPE_LABELS: Record<ContentPieceSummary["type"], string> = {
  video: "Vídeo",
  image: "Imagem",
  audio: "Áudio",
};

export interface PieceAsset {
  type: "image" | "audio" | "video" | "thumbnail" | "subtitle";
  // null when the backend could not sign this asset — it is still listed so
  // the reviewer knows the asset exists and must not decide without it.
  signed_url: string | null;
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

export interface Client {
  id: number;
  tenant_id: number;
  name: string;
  is_active: boolean;
  created_at: string;
}

export interface ClientPayload {
  name: string;
}

export interface SocialAccount {
  id: number;
  client_id: number;
  platform: string;
  external_account_id: string;
  status: string;
  created_at: string;
}

export interface SocialAccountCreatePayload {
  client_id: number;
  platform: string;
  external_account_id: string;
  credentials: string;
}

export interface SocialAccountUpdatePayload {
  external_account_id?: string;
  credentials?: string;
}

export interface Avatar {
  id: number;
  client_id: number;
  name: string;
  reference_image_url: string;
  voice_provider: string | null;
  voice_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ApprovalRule {
  id: number;
  campaign_id: number;
  condition: Record<string, unknown>;
  action: "auto_approve" | "require_review";
  priority: number;
  created_at: string;
}

export interface ApprovalRulePayload {
  campaign_id?: number;
  condition: Record<string, unknown>;
  action: "auto_approve" | "require_review";
  priority: number;
}

export interface GenerationTemplate {
  id: number;
  campaign_id: number;
  type: "video" | "image" | "audio";
  generation_prompt: string | null;
  narration_script: string | null;
  avatar_id: number | null;
  voice_id: string | null;
  is_synthetic_media: boolean;
  content_category: string | null;
  aspect_ratio: string;
  resolution: string | null;
  duration: number | null;
  is_active: boolean;
  created_at: string;
}

export interface GenerationTemplatePayload {
  campaign_id?: number;
  type: "video" | "image" | "audio";
  generation_prompt: string;
  narration_script?: string | null;
  avatar_id?: number | null;
  voice_id?: string | null;
  is_synthetic_media: boolean;
  content_category?: string | null;
  aspect_ratio: string;
  resolution?: string | null;
  duration?: number | null;
}

export interface Provider {
  id: number;
  tenant_id: number;
  kind: "image" | "video" | "voice";
  provider: "wavespeed" | "falai" | "gemini" | "elevenlabs";
  config: Record<string, unknown>;
  priority: number;
  is_active: boolean;
  created_at: string;
}

export interface ProviderCreatePayload {
  kind: "image" | "video" | "voice";
  provider: "wavespeed" | "falai" | "gemini" | "elevenlabs";
  credentials: string;
  config: Record<string, unknown>;
  priority: number;
}

export interface ProviderUpdatePayload {
  credentials?: string;
  config?: Record<string, unknown>;
  priority?: number;
}

export interface AuditLogEntry {
  id: number;
  entity_type: string;
  entity_id: number;
  action: string;
  actor: string;
  // Free-form JSON. Edit events use {field: {before, after}}; others (the
  // scheduler's rejections, publish counts, caption edits) store plain
  // values, so this cannot be typed as the diff shape alone.
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface PieceUpdatePayload {
  generation_prompt?: string | null;
  narration_script?: string | null;
  avatar_id?: number | null;
  voice_id?: string | null;
  content_category?: string | null;
  risk_level?: string | null;
  scheduled_for?: string | null;
}

// --- Calendar (GET /content/ui/calendar) ---

/** Derived on the server from status + scheduled_for + publication_summary.
 * Not a ContentPiece status: the state machine the scheduler depends on stays
 * as it is, and this vocabulary exists only for display. */
export type CalendarState =
  | "draft"
  | "scheduled"
  | "publishing"
  | "published"
  | "failed";

export interface CalendarPlatform {
  platform: string;
  succeeded: number;
  failed: number;
}

export interface CalendarItem {
  id: number;
  campaign_id: number;
  campaign_name: string | null;
  client_id: number | null;
  client_name: string | null;
  type: "video" | "image" | "audio";
  status: string;
  calendar_state: CalendarState;
  scheduled_for: string | null;
  posted_at: string | null;
  title: string;
  thumbnail_url: string | null;
  platforms: CalendarPlatform[];
  /** Publishing has started, so the schedule no longer decides anything and
   * the card must refuse to be dragged. */
  is_locked: boolean;
}

export interface CalendarResponse {
  range: { date_from: string; date_to: string };
  /** Keyed by "all" plus each CalendarState. Counted before the status filter
   * is applied, so the pills show what each option would yield. */
  counts: Record<string, number>;
  items: CalendarItem[];
}

export interface CalendarFilterOption {
  id: string;
  label: string;
}

export interface CalendarFilters {
  clients: CalendarFilterOption[];
  campaigns: CalendarFilterOption[];
  platforms: CalendarFilterOption[];
  accounts: CalendarFilterOption[];
}

// --- Social Agent ---

export interface ProposedPiece {
  type: "image" | "video" | "audio";
  generation_prompt: string;
  narration_script: string | null;
  caption: string | null;
}

export interface AgentProposal {
  summary: string;
  pieces: ProposedPiece[];
  /** True when the LLM was unreachable and this is the deterministic
   * fallback — the UI says so instead of passing it off as generated. */
  is_fallback: boolean;
}

/** A generation step: what the pipeline actually did, per piece. */
export interface GenerationJob {
  id: number;
  kind: string;
  status: string;
  provider: string | null;
  model: string | null;
  attempt_count: number;
  retry_count: number;
  duration_ms: number | null;
  actual_cost: number | null;
  estimated_cost: number | null;
  currency: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}
