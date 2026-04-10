"use client";

import { useState, useCallback } from "react";
import {
  Shield,
  Check,
  X,
  Pencil,
  AlertTriangle,
  ChevronRight,
  ImageIcon,
  ExternalLink,
} from "lucide-react";
import { moderation } from "@/lib/api";
import { withAuditLog } from "@/lib/audit";
import type { ModerationItem, SellerHistory } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { cn, formatCurrency, isOverdue, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/badge";
import { RiskScore } from "@/components/risk-score";
import { SlaTimer } from "@/components/sla-timer";
import { ActionDialog } from "@/components/action-dialog";
import { EmptyState } from "@/components/empty-state";

// ═══════════════════════════════════════════════════════════════
// Moderation Queue
// ═══════════════════════════════════════════════════════════════

export default function ModerationPage() {
  const {
    data: items,
    loading,
    refetch,
  } = useAsync(
    () => moderation.list({ status: "pending_review" }).then((r) => r.data.items as ModerationItem[]),
    []
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sidebarSeller, setSidebarSeller] = useState<SellerHistory | null>(null);
  const [sidebarLoading, setSidebarLoading] = useState(false);

  // Dialog state
  const [dialog, setDialog] = useState<{
    type: "reject" | "require_edit" | "escalate";
    item: ModerationItem;
  } | null>(null);

  const selected = items?.find((i) => i.id === selectedId) ?? null;

  // Sort: AI risk DESC, then wait time ASC (longest first)
  const sorted = items
    ? [...items].sort((a, b) => {
        if (b.ai_risk_score !== a.ai_risk_score)
          return b.ai_risk_score - a.ai_risk_score;
        return (
          new Date(a.submitted_at).getTime() -
          new Date(b.submitted_at).getTime()
        );
      })
    : [];

  const loadSellerHistory = useCallback(async (sellerId: string) => {
    setSidebarLoading(true);
    try {
      const resp = await moderation.sellerHistory(sellerId);
      setSidebarSeller(resp.data as SellerHistory);
    } catch {
      setSidebarSeller(null);
    } finally {
      setSidebarLoading(false);
    }
  }, []);

  const selectItem = useCallback(
    (item: ModerationItem) => {
      setSelectedId(item.id);
      loadSellerHistory(item.seller_id);
    },
    [loadSellerHistory]
  );

  // ── Actions ──────────────────────────────────────────────

  const handleApprove = async (item: ModerationItem) => {
    await withAuditLog(
      {
        action: "approve_listing",
        targetType: "listing",
        targetId: item.listing_id,
        reason: "Approved after review",
      },
      () => moderation.approve(item.id)
    );
    refetch();
  };

  const handleReject = async (item: ModerationItem, reason: string) => {
    await withAuditLog(
      {
        action: "reject_listing",
        targetType: "listing",
        targetId: item.listing_id,
        reason,
      },
      () => moderation.reject(item.id, reason)
    );
    refetch();
  };

  const handleRequireEdit = async (item: ModerationItem, reason: string) => {
    await withAuditLog(
      {
        action: "require_edit",
        targetType: "listing",
        targetId: item.listing_id,
        reason,
      },
      () => moderation.requireEdit(item.id, reason)
    );
    refetch();
  };

  const handleEscalate = async (item: ModerationItem, reason: string) => {
    await withAuditLog(
      {
        action: "escalate_listing",
        targetType: "listing",
        targetId: item.listing_id,
        reason,
      },
      () => moderation.escalate(item.id, reason)
    );
    refetch();
  };

  // ── Render ───────────────────────────────────────────────

  if (loading) {
    return <ModerationSkeleton />;
  }

  if (!sorted.length) {
    return (
      <EmptyState
        icon={Shield}
        title="Queue is clear"
        description="No listings awaiting review right now."
      />
    );
  }

  return (
    <>
      <div className="flex gap-6 h-[calc(100vh-8rem)]">
        {/* ── List panel ───────────────────────────────────── */}
        <div className="w-[420px] flex-shrink-0 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-lg font-bold text-navy font-sora">
              Moderation Queue
            </h1>
            <Badge variant="navy">{sorted.length} pending</Badge>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {sorted.map((item) => {
              const overdue = isOverdue(item.submitted_at, 2);
              const isSelected = item.id === selectedId;

              return (
                <button
                  key={item.id}
                  onClick={() => selectItem(item)}
                  className={cn(
                    "w-full text-left card transition-all",
                    isSelected && "ring-2 ring-navy",
                    overdue && !isSelected && "border-ember/40 bg-ember/[0.03]"
                  )}
                >
                  <div className="flex items-start gap-3">
                    {/* Thumbnail */}
                    <div className="w-14 h-14 rounded-lg bg-sand flex-shrink-0 overflow-hidden">
                      {item.image_urls[0] ? (
                        <img
                          src={item.image_urls[0]}
                          alt=""
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center">
                          <ImageIcon size={16} className="text-mist" />
                        </div>
                      )}
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <RiskScore score={item.ai_risk_score} />
                        <span className="text-sm font-semibold text-ink truncate">
                          {item.title_en}
                        </span>
                      </div>
                      <p className="text-xs text-mist mt-0.5 truncate">
                        {item.seller_name} · {item.category}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <SlaTimer since={item.submitted_at} slaHours={2} />
                        {item.ai_flags.length > 0 && (
                          <Badge variant="amber">
                            {item.ai_flags.length} flag
                            {item.ai_flags.length > 1 ? "s" : ""}
                          </Badge>
                        )}
                      </div>
                    </div>

                    <ChevronRight
                      size={14}
                      className="text-mist mt-1 flex-shrink-0"
                    />
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* ── Detail panel ─────────────────────────────────── */}
        {selected ? (
          <div className="flex-1 flex gap-6 min-w-0">
            {/* Listing detail */}
            <div className="flex-1 overflow-y-auto space-y-4">
              <div className="card">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-base font-bold text-navy font-sora">
                    {selected.title_en}
                  </h2>
                  <RiskScore score={selected.ai_risk_score} />
                </div>
                <p className="text-sm text-mist mb-1">{selected.title_ar}</p>

                {/* Images */}
                <div className="flex gap-2 mt-3 overflow-x-auto pb-2">
                  {selected.image_urls.map((url, i) => (
                    <img
                      key={i}
                      src={url}
                      alt={`Photo ${i + 1}`}
                      className="w-32 h-32 object-cover rounded-lg flex-shrink-0 border border-sand"
                    />
                  ))}
                  {selected.image_urls.length === 0 && (
                    <div className="w-32 h-32 rounded-lg bg-sand flex items-center justify-center">
                      <ImageIcon size={20} className="text-mist" />
                    </div>
                  )}
                </div>

                {/* Details */}
                <div className="grid grid-cols-2 gap-3 mt-4">
                  <DetailRow label="Category" value={selected.category} />
                  <DetailRow label="Condition" value={selected.condition} />
                  <DetailRow
                    label="Starting price"
                    value={formatCurrency(
                      selected.starting_price,
                      selected.currency
                    )}
                  />
                  <DetailRow
                    label="Submitted"
                    value={timeAgo(selected.submitted_at)}
                  />
                </div>

                {/* AI flags */}
                {selected.ai_flags.length > 0 && (
                  <div className="mt-4 p-3 bg-amber-50 rounded-lg border border-amber-200">
                    <div className="flex items-center gap-1 text-amber-700 text-xs font-semibold mb-2">
                      <AlertTriangle size={14} />
                      AI Flags
                    </div>
                    <ul className="space-y-1">
                      {selected.ai_flags.map((flag, i) => (
                        <li key={i} className="text-xs text-amber-800">
                          • {flag}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* ── Action buttons ──────────────────────────── */}
              <div className="card">
                <h3 className="text-sm font-bold text-navy mb-3">Actions</h3>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => handleApprove(selected)}
                    className="btn-primary inline-flex items-center gap-1.5"
                  >
                    <Check size={14} />
                    Approve
                  </button>
                  <button
                    onClick={() =>
                      setDialog({ type: "reject", item: selected })
                    }
                    className="btn-danger inline-flex items-center gap-1.5"
                  >
                    <X size={14} />
                    Reject
                  </button>
                  <button
                    onClick={() =>
                      setDialog({ type: "require_edit", item: selected })
                    }
                    className="btn-outline inline-flex items-center gap-1.5"
                  >
                    <Pencil size={14} />
                    Require Edit
                  </button>
                  <button
                    onClick={() =>
                      setDialog({ type: "escalate", item: selected })
                    }
                    className="btn-gold inline-flex items-center gap-1.5"
                  >
                    <AlertTriangle size={14} />
                    Escalate
                  </button>
                </div>
              </div>
            </div>

            {/* ── Seller sidebar ───────────────────────────── */}
            <div className="w-64 flex-shrink-0 overflow-y-auto">
              <SellerSidebar
                seller={sidebarSeller}
                loading={sidebarLoading}
              />
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-mist">
            Select a listing to review
          </div>
        )}
      </div>

      {/* ── Dialogs ──────────────────────────────────────── */}
      {dialog && (
        <ActionDialog
          open
          onClose={() => setDialog(null)}
          title={
            dialog.type === "reject"
              ? "Reject Listing"
              : dialog.type === "require_edit"
                ? "Require Edit"
                : "Escalate Listing"
          }
          description={`${dialog.item.title_en} by ${dialog.item.seller_name}`}
          confirmLabel={
            dialog.type === "reject"
              ? "Reject"
              : dialog.type === "require_edit"
                ? "Send back"
                : "Escalate"
          }
          confirmVariant={dialog.type === "reject" ? "danger" : "primary"}
          onConfirm={(reason) => {
            if (dialog.type === "reject")
              return handleReject(dialog.item, reason);
            if (dialog.type === "require_edit")
              return handleRequireEdit(dialog.item, reason);
            return handleEscalate(dialog.item, reason);
          }}
        />
      )}
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] text-mist uppercase tracking-wider">
        {label}
      </dt>
      <dd className="text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

function SellerSidebar({
  seller,
  loading,
}: {
  seller: SellerHistory | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="card animate-pulse space-y-3">
        <div className="h-4 bg-sand rounded w-2/3" />
        <div className="h-3 bg-sand rounded w-1/2" />
        <div className="h-3 bg-sand rounded w-full" />
        <div className="h-3 bg-sand rounded w-3/4" />
      </div>
    );
  }

  if (!seller) {
    return (
      <div className="card text-center text-sm text-mist py-8">
        No seller data
      </div>
    );
  }

  const tierColor = {
    elite: "emerald",
    pro: "gold",
    trusted: "navy",
    starter: "mist",
  } as const;

  return (
    <div className="space-y-3">
      <div className="card">
        <h3 className="text-sm font-bold text-navy mb-2">Seller Profile</h3>
        <p className="text-sm font-medium text-ink">{seller.name_ar}</p>
        <p className="text-xs text-mist">{seller.phone}</p>
        <div className="flex items-center gap-2 mt-2">
          <Badge
            variant={
              tierColor[seller.ats_tier as keyof typeof tierColor] ?? "mist"
            }
          >
            {seller.ats_tier.toUpperCase()}
          </Badge>
          <span className="text-xs font-bold text-navy font-mono">
            ATS {seller.ats_score}
          </span>
        </div>

        {seller.strikes > 0 && (
          <div className="mt-2">
            <Badge variant="ember">
              {seller.strikes} strike{seller.strikes > 1 ? "s" : ""}
            </Badge>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 mt-3 text-xs">
          <div>
            <span className="text-mist block">Listings</span>
            <span className="font-semibold text-ink">
              {seller.total_listings}
            </span>
          </div>
          <div>
            <span className="text-mist block">Completed</span>
            <span className="font-semibold text-ink">
              {seller.completed_sales}
            </span>
          </div>
          <div>
            <span className="text-mist block">Active</span>
            <span className="font-semibold text-ink">
              {seller.active_listings}
            </span>
          </div>
          <div>
            <span className="text-mist block">Dispute rate</span>
            <span className="font-semibold text-ink">
              {(seller.dispute_rate * 100).toFixed(1)}%
            </span>
          </div>
        </div>
      </div>

      {/* Past listings */}
      <div className="card">
        <h3 className="text-sm font-bold text-navy mb-2">
          Past Reviews ({seller.past_listings.length})
        </h3>
        <div className="space-y-2 max-h-60 overflow-y-auto">
          {seller.past_listings.slice(0, 10).map((listing) => (
            <div
              key={listing.id}
              className="flex items-center justify-between text-xs"
            >
              <span className="truncate text-ink max-w-[140px]">
                {listing.title}
              </span>
              <Badge
                variant={
                  listing.moderation_result === "approved"
                    ? "emerald"
                    : listing.moderation_result === "rejected"
                      ? "ember"
                      : "mist"
                }
              >
                {listing.moderation_result}
              </Badge>
            </div>
          ))}
          {seller.past_listings.length === 0 && (
            <p className="text-xs text-mist">No past listings</p>
          )}
        </div>
      </div>
    </div>
  );
}

function ModerationSkeleton() {
  return (
    <div className="flex gap-6">
      <div className="w-[420px] space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card animate-pulse">
            <div className="flex gap-3">
              <div className="w-14 h-14 bg-sand rounded-lg" />
              <div className="flex-1 space-y-2">
                <div className="h-3 bg-sand rounded w-3/4" />
                <div className="h-2.5 bg-sand rounded w-1/2" />
                <div className="h-2 bg-sand rounded w-1/3" />
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 card animate-pulse">
        <div className="h-4 bg-sand rounded w-1/3 mb-4" />
        <div className="h-32 bg-sand rounded" />
      </div>
    </div>
  );
}
