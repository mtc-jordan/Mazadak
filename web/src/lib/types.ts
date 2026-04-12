// ═══════════════════════════════════════════════════════════════
// Shared types for MZADAK Admin Panel
// ═══════════════════════════════════════════════════════════════

// ── Moderation ──────────────────────────────────────────────

export type ModerationStatus =
  | "pending_review"
  | "approved"
  | "rejected"
  | "requires_edit"
  | "escalated";

export interface ModerationItem {
  id: string;
  listing_id: string;
  title_en: string;
  title_ar: string;
  image_urls: string[];
  category: string;
  condition: string;
  starting_price: number;
  currency: string;
  ai_risk_score: number; // 0-100
  ai_flags: string[];
  status: ModerationStatus;
  submitted_at: string;
  seller_id: string;
  seller_name: string;
  seller_ats_score: number;
  seller_strikes: number;
  seller_total_listings: number;
  reviewer_id?: string;
  reviewed_at?: string;
  rejection_reason?: string;
}

export interface SellerHistory {
  user_id: string;
  name_ar: string;
  phone: string;
  ats_score: number;
  ats_tier: string;
  strikes: number;
  total_listings: number;
  active_listings: number;
  completed_sales: number;
  dispute_rate: number;
  member_since: string;
  past_listings: {
    id: string;
    title: string;
    status: string;
    moderation_result: string;
    submitted_at: string;
  }[];
}

// ── Disputes ────────────────────────────────────────────────

export type DisputeStatus =
  | "open"
  | "under_review"
  | "awaiting_seller"
  | "awaiting_buyer"
  | "resolved"
  | "escalated";

export type DisputeOutcome =
  | "full_refund"
  | "partial_refund"
  | "replacement"
  | "no_action"
  | "buyer_fault"
  | "seller_fault";

export interface Dispute {
  id: string;
  escrow_id: string;
  listing_id: string;
  listing_title: string;
  listing_image_url: string;
  buyer_id: string;
  buyer_name: string;
  seller_id: string;
  seller_name: string;
  reason: string;
  description: string;
  desired_resolution: string;
  status: DisputeStatus;
  amount: number;
  currency: string;
  buyer_photos: EvidencePhoto[];
  seller_photos: EvidencePhoto[];
  listing_photos: string[];
  escrow_events: EscrowEvent[];
  opened_at: string;
  under_review_since?: string;
  resolved_at?: string;
  ruling?: DisputeRuling;
}

export interface EvidencePhoto {
  url: string;
  hash: string;
  uploaded_at: string;
}

export interface EscrowEvent {
  type: string;
  timestamp: string;
  actor?: string;
  details?: string;
}

export interface DisputeRuling {
  outcome: DisputeOutcome;
  reason_code: string;
  reason_text: string;
  refund_amount?: number;
  admin_id: string;
  ruled_at: string;
}

export const DISPUTE_REASON_CODES = [
  { code: "item_not_as_described", label: "Item not as described" },
  { code: "item_not_received", label: "Item not received" },
  { code: "item_damaged", label: "Item damaged in transit" },
  { code: "counterfeit", label: "Counterfeit item" },
  { code: "wrong_item", label: "Wrong item received" },
  { code: "seller_unresponsive", label: "Seller unresponsive" },
  { code: "buyer_remorse", label: "Buyer remorse / changed mind" },
  { code: "insufficient_evidence", label: "Insufficient evidence" },
  { code: "mutual_resolution", label: "Mutual resolution" },
  { code: "other", label: "Other" },
] as const;

// ── Users ───────────────────────────────────────────────────

export type UserRole = "buyer" | "seller" | "pro_seller" | "admin";
export type UserStatus = "active" | "warned" | "suspended" | "banned";
export type KycStatus =
  | "not_started"
  | "none"
  | "pending"
  | "pending_review"
  | "verified"
  | "rejected";

// ── KYC Review (admin queue) ────────────────────────────────

export type KycDocumentType = "id_front" | "id_back" | "selfie";

export interface KycQueueItem {
  id: string; // document id
  user_id: string;
  user_phone: string;
  document_type: KycDocumentType;
  s3_key: string;
  rekognition_confidence: number | null;
  status: "pending_review";
  uploaded_at: string;
}

/** Aggregated view: one row per user, with their three docs grouped. */
export interface KycReviewUser {
  user_id: string;
  user_phone: string;
  /** Lowest non-null confidence across documents (None when Rekognition was unavailable). */
  confidence: number | null;
  uploaded_at: string;
  documents: KycQueueItem[];
}

export interface User {
  id: string;
  phone: string;
  full_name_ar: string;
  full_name_en?: string;
  email?: string;
  role: UserRole;
  status: UserStatus;
  kyc_status: KycStatus;
  ats_score: number;
  ats_tier: string;
  ats_components: AtsComponent[];
  strikes: Strike[];
  total_listings: number;
  total_bids: number;
  total_purchases: number;
  total_sales: number;
  dispute_count: number;
  member_since: string;
  last_active: string;
}

export interface AtsComponent {
  key: string;
  label: string;
  value: number; // 0-1 normalized
  max_points: number;
  earned_points: number;
}

export interface Strike {
  id: string;
  type: string;
  reason: string;
  issued_by: string;
  issued_at: string;
  expires_at?: string;
  is_active: boolean;
}

export type AdminAction =
  | "warn"
  | "suspend"
  | "ban"
  | "restore"
  | "approve_listing"
  | "reject_listing"
  | "require_edit"
  | "escalate_listing"
  | "resolve_dispute"
  | "approve_kyc"
  | "reject_kyc";

export interface AuditLogEntry {
  action: AdminAction;
  target_type: "user" | "listing" | "dispute";
  target_id: string;
  reason: string;
  metadata?: Record<string, unknown>;
}

// ── B2B Tender Rooms ────────────────────────────────────────

export type B2BRoomStatus =
  | "open"
  | "closed"
  | "cancelled"
  | "results_announced";

export interface B2BRoomListItem {
  id: string;
  client_name: string;
  client_name_ar?: string | null;
  tender_reference: string;
  status: B2BRoomStatus;
  submission_deadline: string;
  sealed: boolean;
  min_lot_amount: number; // cents
  estimated_value?: number | null;
  bid_count: number;
  invitation_count: number;
  created_at: string;
}

export interface B2BRoomListResponse {
  items: B2BRoomListItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface B2BBidItem {
  id: string;
  bidder_id: string;
  bidder_name?: string | null;
  amount: number; // cents
  notes?: string | null;
  validity_days: number;
  is_winner: boolean;
  submitted_at: string;
  submission_ref?: string | null;
}

export interface B2BInvitationItem {
  id: string;
  user_id: string;
  user_name?: string | null;
  status: "pending" | "accepted" | "declined" | "revoked";
  min_ats_score?: number | null;
  min_kyc_level?: string | null;
  invited_at: string;
  responded_at?: string | null;
}

export interface B2BRoomDetail {
  id: string;
  client_name: string;
  client_name_ar?: string | null;
  tender_reference: string;
  description?: string | null;
  status: B2BRoomStatus;
  submission_deadline: string;
  results_announced_at?: string | null;
  sealed: boolean;
  min_lot_amount: number;
  estimated_value?: number | null;
  client_logo_url?: string | null;
  documents: Array<{ name?: string; size?: string; url?: string }>;
  created_at: string;
  bids: B2BBidItem[];
  invitations: B2BInvitationItem[];
}

export interface B2BAnalytics {
  room_id: string;
  invited_count: number;
  bid_count: number;
  participation_rate: number; // 0..1
  avg_bid_amount?: number | null;
  min_bid_amount?: number | null;
  max_bid_amount?: number | null;
  price_vs_estimate_ratio?: number | null;
  winner_amount?: number | null;
  time_to_close_hours?: number | null;
}

export interface B2BCreateRoomRequest {
  client_name: string;
  client_name_ar?: string | null;
  tender_reference: string;
  description?: string | null;
  submission_deadline: string; // ISO
  sealed?: boolean;
  min_lot_amount?: number; // cents, default 1_000_000
  estimated_value?: number | null;
  client_logo_url?: string | null;
  documents?: Array<Record<string, unknown>>;
}

export interface B2BInviteRequest {
  invitations: Array<{
    user_id: string;
    min_ats_score?: number | null;
    min_kyc_level?: string | null;
  }>;
}
