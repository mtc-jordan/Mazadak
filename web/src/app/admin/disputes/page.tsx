"use client";

import { useState, useCallback } from "react";
import {
  Scale,
  ChevronRight,
  ImageIcon,
  Clock,
  FileText,
  Camera,
  Gavel,
  AlertCircle,
} from "lucide-react";
import { disputes } from "@/lib/api";
import { withAuditLog } from "@/lib/audit";
import type { Dispute, DisputeOutcome, EscrowEvent, EvidencePhoto } from "@/lib/types";
import { DISPUTE_REASON_CODES } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { cn, formatCurrency, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/badge";
import { SlaTimer } from "@/components/sla-timer";
import { EmptyState } from "@/components/empty-state";

// ═══════════════════════════════════════════════════════════════
// Dispute Queue
// ═══════════════════════════════════════════════════════════════

export default function DisputesPage() {
  const {
    data: items,
    loading,
    refetch,
  } = useAsync(
    () =>
      disputes
        .list({ status: "under_review" })
        .then((r) => r.data.items as Dispute[]),
    []
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<"evidence" | "timeline" | "ruling">(
    "evidence"
  );

  const sorted = items
    ? [...items].sort(
        (a, b) =>
          new Date(a.under_review_since ?? a.opened_at).getTime() -
          new Date(b.under_review_since ?? b.opened_at).getTime()
      )
    : [];

  const selected = sorted.find((d) => d.id === selectedId) ?? null;

  if (loading) return <DisputeSkeleton />;

  if (!sorted.length) {
    return (
      <EmptyState
        icon={Scale}
        title="No open disputes"
        description="All disputes have been resolved."
      />
    );
  }

  return (
    <div className="flex gap-6 h-[calc(100vh-8rem)]">
      {/* ── List panel ───────────────────────────────────── */}
      <div className="w-[380px] flex-shrink-0 flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-lg font-bold text-navy font-sora">
            Dispute Queue
          </h1>
          <Badge variant="ember">{sorted.length} open</Badge>
        </div>

        <div className="flex-1 overflow-y-auto space-y-2 pr-1">
          {sorted.map((d) => (
            <button
              key={d.id}
              onClick={() => {
                setSelectedId(d.id);
                setTab("evidence");
              }}
              className={cn(
                "w-full text-left card transition-all",
                d.id === selectedId && "ring-2 ring-navy"
              )}
            >
              <div className="flex items-start gap-3">
                <div className="w-12 h-12 rounded-lg bg-sand flex-shrink-0 overflow-hidden">
                  {d.listing_image_url ? (
                    <img
                      src={d.listing_image_url}
                      alt=""
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImageIcon size={14} className="text-mist" />
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-ink truncate">
                    {d.listing_title}
                  </p>
                  <p className="text-xs text-mist truncate">
                    {d.reason} · {formatCurrency(d.amount, d.currency)}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <SlaTimer
                      since={d.under_review_since ?? d.opened_at}
                    />
                    <StatusBadge status={d.status} />
                  </div>
                </div>
                <ChevronRight size={14} className="text-mist mt-1" />
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* ── Detail panel ─────────────────────────────────── */}
      {selected ? (
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Header */}
          <div className="card mb-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-navy font-sora">
                  {selected.listing_title}
                </h2>
                <p className="text-xs text-mist mt-0.5">
                  {selected.buyer_name} (Buyer) vs {selected.seller_name}{" "}
                  (Seller) · {formatCurrency(selected.amount, selected.currency)}
                </p>
              </div>
              <StatusBadge status={selected.status} />
            </div>
            <div className="flex items-center gap-4 mt-2 text-xs text-mist">
              <span>Reason: {selected.reason}</span>
              <span>Desired: {selected.desired_resolution}</span>
              <span>Opened: {timeAgo(selected.opened_at)}</span>
            </div>
          </div>

          {/* Tab bar */}
          <div className="flex gap-1 mb-4">
            {(
              [
                { key: "evidence", label: "Evidence", icon: Camera },
                { key: "timeline", label: "Event Log", icon: Clock },
                { key: "ruling", label: "Ruling", icon: Gavel },
              ] as const
            ).map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-semibold transition-colors",
                  tab === t.key
                    ? "bg-navy text-white"
                    : "bg-white text-mist hover:text-ink border border-sand"
                )}
              >
                <t.icon size={14} />
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto">
            {tab === "evidence" && <EvidenceTab dispute={selected} />}
            {tab === "timeline" && (
              <TimelineTab events={selected.escrow_events} />
            )}
            {tab === "ruling" && (
              <RulingTab dispute={selected} onSubmit={refetch} />
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-sm text-mist">
          Select a dispute to review
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Evidence Tab — side-by-side comparison
// ═══════════════════════════════════════════════════════════════

function EvidenceTab({ dispute }: { dispute: Dispute }) {
  const [expandedImg, setExpandedImg] = useState<string | null>(null);

  return (
    <>
      <div className="grid grid-cols-3 gap-4">
        {/* Buyer photos */}
        <div>
          <h3 className="text-sm font-bold text-navy mb-2 flex items-center gap-1">
            <AlertCircle size={14} className="text-ember" />
            Buyer Evidence ({dispute.buyer_photos.length})
          </h3>
          <PhotoGrid
            photos={dispute.buyer_photos}
            onExpand={setExpandedImg}
          />
          {dispute.description && (
            <div className="mt-3 p-3 bg-ember/5 rounded-lg border border-ember/10">
              <p className="text-xs text-ink leading-relaxed">
                {dispute.description}
              </p>
            </div>
          )}
        </div>

        {/* Seller photos */}
        <div>
          <h3 className="text-sm font-bold text-navy mb-2">
            Seller Response ({dispute.seller_photos.length})
          </h3>
          <PhotoGrid
            photos={dispute.seller_photos}
            onExpand={setExpandedImg}
          />
          {dispute.seller_photos.length === 0 && (
            <p className="text-xs text-mist mt-2">
              No seller evidence submitted yet
            </p>
          )}
        </div>

        {/* Listing photos */}
        <div>
          <h3 className="text-sm font-bold text-navy mb-2">
            Original Listing ({dispute.listing_photos.length})
          </h3>
          <div className="space-y-2">
            {dispute.listing_photos.map((url, i) => (
              <img
                key={i}
                src={url}
                alt={`Listing ${i + 1}`}
                onClick={() => setExpandedImg(url)}
                className="w-full aspect-square object-cover rounded-lg border border-sand cursor-pointer hover:opacity-80 transition-opacity"
              />
            ))}
          </div>
        </div>
      </div>

      {/* Expanded image modal */}
      {expandedImg && (
        <div
          className="fixed inset-0 z-50 bg-ink/80 flex items-center justify-center cursor-pointer"
          onClick={() => setExpandedImg(null)}
        >
          <img
            src={expandedImg}
            alt="Evidence"
            className="max-w-[80vw] max-h-[80vh] rounded-xl shadow-2xl"
          />
        </div>
      )}
    </>
  );
}

function PhotoGrid({
  photos,
  onExpand,
}: {
  photos: EvidencePhoto[];
  onExpand: (url: string) => void;
}) {
  return (
    <div className="space-y-2">
      {photos.map((p, i) => (
        <div key={i} className="relative group">
          <img
            src={p.url}
            alt={`Evidence ${i + 1}`}
            onClick={() => onExpand(p.url)}
            className="w-full aspect-square object-cover rounded-lg border border-sand cursor-pointer hover:opacity-80 transition-opacity"
          />
          <span className="absolute bottom-1 left-1 px-1.5 py-0.5 bg-black/60 text-white text-[9px] font-mono rounded">
            #{p.hash.slice(0, 8)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// Timeline Tab — full escrow event log
// ═══════════════════════════════════════════════════════════════

function TimelineTab({ events }: { events: EscrowEvent[] }) {
  if (!events.length) {
    return <p className="text-sm text-mist py-8 text-center">No events</p>;
  }

  return (
    <div className="card">
      <h3 className="text-sm font-bold text-navy mb-3">Escrow Event Log</h3>
      <div className="space-y-0">
        {events.map((ev, i) => (
          <div key={i} className="flex gap-3">
            {/* Timeline rail */}
            <div className="flex flex-col items-center">
              <div className="w-2.5 h-2.5 rounded-full bg-navy mt-1.5" />
              {i < events.length - 1 && (
                <div className="w-px flex-1 bg-sand" />
              )}
            </div>
            {/* Content */}
            <div className="pb-4 min-w-0">
              <p className="text-sm font-medium text-ink">
                {eventLabel(ev.type)}
              </p>
              {ev.details && (
                <p className="text-xs text-mist mt-0.5">{ev.details}</p>
              )}
              <p className="text-[11px] text-mist mt-0.5">
                {timeAgo(ev.timestamp)}
                {ev.actor && ` · ${ev.actor}`}
              </p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function eventLabel(type: string): string {
  const labels: Record<string, string> = {
    payment_received: "Payment received",
    shipping_requested: "Shipping requested",
    tracking_submitted: "Tracking submitted",
    in_transit: "Package in transit",
    delivered: "Delivered",
    delivery_confirmed: "Delivery confirmed",
    funds_released: "Funds released",
    dispute_opened: "Dispute opened",
    dispute_resolved: "Dispute resolved",
    refunded: "Refunded",
  };
  return labels[type] ?? type.replace(/_/g, " ");
}

// ═══════════════════════════════════════════════════════════════
// Ruling Tab — admin ruling form
// ═══════════════════════════════════════════════════════════════

function RulingTab({
  dispute,
  onSubmit,
}: {
  dispute: Dispute;
  onSubmit: () => void;
}) {
  const [outcome, setOutcome] = useState<DisputeOutcome>("full_refund");
  const [reasonCode, setReasonCode] = useState(
    DISPUTE_REASON_CODES[0].code
  );
  const [reasonText, setReasonText] = useState("");
  const [refundAmount, setRefundAmount] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = !submitting && reasonText.trim().length >= 100;

  const outcomes: { value: DisputeOutcome; label: string }[] = [
    { value: "full_refund", label: "Full refund to buyer" },
    { value: "partial_refund", label: "Partial refund" },
    { value: "replacement", label: "Require replacement" },
    { value: "no_action", label: "No action needed" },
    { value: "buyer_fault", label: "Buyer at fault" },
    { value: "seller_fault", label: "Seller at fault" },
  ];

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);

    try {
      await withAuditLog(
        {
          action: "resolve_dispute",
          targetType: "dispute",
          targetId: dispute.id,
          reason: reasonText.trim(),
          metadata: { outcome, reason_code: reasonCode },
        },
        () =>
          disputes.resolve(dispute.id, {
            outcome,
            reason_code: reasonCode,
            reason_text: reasonText.trim(),
            refund_amount:
              outcome === "partial_refund" && refundAmount
                ? parseFloat(refundAmount)
                : undefined,
          })
      );
      onSubmit();
    } catch (e: any) {
      setError(e?.message ?? "Failed to submit ruling");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="card max-w-2xl">
      <h3 className="text-sm font-bold text-navy mb-4 flex items-center gap-2">
        <Gavel size={16} />
        Issue Ruling
      </h3>

      {/* Outcome selector */}
      <label className="text-xs font-semibold text-mist uppercase tracking-wider block mb-2">
        Outcome
      </label>
      <div className="grid grid-cols-2 gap-2 mb-4">
        {outcomes.map((o) => (
          <button
            key={o.value}
            onClick={() => setOutcome(o.value)}
            className={cn(
              "text-left px-3 py-2 rounded-lg border text-sm transition-colors",
              outcome === o.value
                ? "border-navy bg-navy/5 text-navy font-semibold"
                : "border-sand text-mist hover:border-navy/30"
            )}
          >
            {o.label}
          </button>
        ))}
      </div>

      {/* Partial refund amount */}
      {outcome === "partial_refund" && (
        <div className="mb-4">
          <label className="text-xs font-semibold text-mist uppercase tracking-wider block mb-1">
            Refund Amount ({dispute.currency})
          </label>
          <input
            type="number"
            step="0.001"
            value={refundAmount}
            onChange={(e) => setRefundAmount(e.target.value)}
            placeholder={`Max: ${dispute.amount}`}
            className="w-48 border border-sand rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-navy"
          />
        </div>
      )}

      {/* Reason code */}
      <label className="text-xs font-semibold text-mist uppercase tracking-wider block mb-2">
        Reason Code
      </label>
      <select
        value={reasonCode}
        onChange={(e) => setReasonCode(e.target.value)}
        className="w-full border border-sand rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-navy mb-4 bg-white"
      >
        {DISPUTE_REASON_CODES.map((rc) => (
          <option key={rc.code} value={rc.code}>
            {rc.label}
          </option>
        ))}
      </select>

      {/* Reason text */}
      <label className="text-xs font-semibold text-mist uppercase tracking-wider block mb-2">
        Detailed Reasoning (min 100 characters)
      </label>
      <textarea
        value={reasonText}
        onChange={(e) => setReasonText(e.target.value)}
        rows={5}
        placeholder="Explain your ruling in detail..."
        className="w-full border border-sand rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-navy resize-none"
      />
      <p
        className={cn(
          "text-xs mt-1",
          reasonText.length >= 100 ? "text-emerald" : "text-mist"
        )}
      >
        {reasonText.length}/100 min characters
      </p>

      {error && (
        <div className="mt-3 p-2 bg-ember/10 rounded-lg text-xs text-ember">
          {error}
        </div>
      )}

      {/* Submit */}
      <div className="mt-5 flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          className={cn(
            "btn-primary inline-flex items-center gap-1.5",
            !canSubmit && "opacity-40 cursor-not-allowed"
          )}
        >
          {submitting ? (
            <span className="inline-flex items-center gap-2">
              <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Submitting...
            </span>
          ) : (
            <>
              <Gavel size={14} />
              Submit Ruling
            </>
          )}
        </button>
        <span className="text-xs text-mist">
          This action is final and will be logged.
        </span>
      </div>
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const variant = {
    open: "amber",
    under_review: "navy",
    awaiting_seller: "gold",
    awaiting_buyer: "gold",
    resolved: "emerald",
    escalated: "ember",
  } as const;
  return (
    <Badge
      variant={variant[status as keyof typeof variant] ?? "mist"}
    >
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

function DisputeSkeleton() {
  return (
    <div className="flex gap-6">
      <div className="w-[380px] space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card animate-pulse">
            <div className="flex gap-3">
              <div className="w-12 h-12 bg-sand rounded-lg" />
              <div className="flex-1 space-y-2">
                <div className="h-3 bg-sand rounded w-3/4" />
                <div className="h-2.5 bg-sand rounded w-1/2" />
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 card animate-pulse">
        <div className="h-4 bg-sand rounded w-1/3 mb-4" />
        <div className="h-40 bg-sand rounded" />
      </div>
    </div>
  );
}
