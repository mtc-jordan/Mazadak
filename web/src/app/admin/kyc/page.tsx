"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import {
  IdCard,
  Check,
  X,
  ChevronRight,
  ImageIcon,
  AlertTriangle,
} from "lucide-react";
import { kyc } from "@/lib/api";
import { withAuditLog } from "@/lib/audit";
import type { KycQueueItem, KycReviewUser } from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/badge";
import { ActionDialog } from "@/components/action-dialog";
import { EmptyState } from "@/components/empty-state";

// ═══════════════════════════════════════════════════════════════
// KYC Review Queue
//
// Backend returns one row per UserKycDocument; we group by user_id so
// the reviewer sees one card per pending user with all 3 documents
// (id_front, id_back, selfie) shown side by side.
// ═══════════════════════════════════════════════════════════════

const DOC_LABELS: Record<string, string> = {
  id_front: "ID front",
  id_back: "ID back",
  selfie: "Selfie",
};

function groupByUser(items: KycQueueItem[]): KycReviewUser[] {
  const byUser = new Map<string, KycReviewUser>();
  for (const item of items) {
    const existing = byUser.get(item.user_id);
    if (!existing) {
      byUser.set(item.user_id, {
        user_id: item.user_id,
        user_phone: item.user_phone,
        confidence: item.rekognition_confidence,
        uploaded_at: item.uploaded_at,
        documents: [item],
      });
    } else {
      existing.documents.push(item);
      // Use the lowest non-null confidence — that's the most useful signal
      if (
        item.rekognition_confidence !== null &&
        (existing.confidence === null ||
          item.rekognition_confidence < existing.confidence)
      ) {
        existing.confidence = item.rekognition_confidence;
      }
      if (item.uploaded_at < existing.uploaded_at) {
        existing.uploaded_at = item.uploaded_at;
      }
    }
  }
  return Array.from(byUser.values());
}

export default function KycReviewPage() {
  const {
    data: items,
    loading,
    refetch,
  } = useAsync(
    () => kyc.queue().then((r) => r.data as KycQueueItem[]),
    []
  );

  const users = useMemo(() => (items ? groupByUser(items) : []), [items]);

  // Sort: oldest upload first (FIFO — fairest for users waiting)
  const sorted = useMemo(
    () =>
      [...users].sort(
        (a, b) =>
          new Date(a.uploaded_at).getTime() -
          new Date(b.uploaded_at).getTime()
      ),
    [users]
  );

  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const selected = sorted.find((u) => u.user_id === selectedUserId) ?? null;

  // Auto-select the first user when the queue loads
  useEffect(() => {
    if (!selectedUserId && sorted.length > 0) {
      setSelectedUserId(sorted[0].user_id);
    }
    // If the current selection is no longer in the queue (just approved/rejected),
    // jump to the next one.
    if (selectedUserId && !sorted.find((u) => u.user_id === selectedUserId)) {
      setSelectedUserId(sorted[0]?.user_id ?? null);
    }
  }, [sorted, selectedUserId]);

  const [rejectDialogUser, setRejectDialogUser] =
    useState<KycReviewUser | null>(null);

  // ── Actions ──────────────────────────────────────────────

  const handleApprove = async (u: KycReviewUser) => {
    await withAuditLog(
      {
        action: "approve_kyc",
        targetType: "user",
        targetId: u.user_id,
        reason: "KYC documents verified after manual review",
      },
      () => kyc.approve(u.user_id)
    );
    refetch();
  };

  const handleReject = async (u: KycReviewUser, reason: string) => {
    await withAuditLog(
      {
        action: "reject_kyc",
        targetType: "user",
        targetId: u.user_id,
        reason,
      },
      () => kyc.reject(u.user_id, reason)
    );
    refetch();
  };

  // ── Render ───────────────────────────────────────────────

  if (loading) {
    return <KycSkeleton />;
  }

  if (!sorted.length) {
    return (
      <EmptyState
        icon={IdCard}
        title="No KYC reviews pending"
        description="Borderline-confidence submissions will appear here for manual review."
      />
    );
  }

  return (
    <>
      <div className="flex gap-6 h-[calc(100vh-8rem)]">
        {/* ── List panel ───────────────────────────────────── */}
        <div className="w-[380px] flex-shrink-0 flex flex-col">
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-lg font-bold text-navy font-sora">
              KYC Review Queue
            </h1>
            <Badge variant="navy">{sorted.length} pending</Badge>
          </div>

          <div className="flex-1 overflow-y-auto space-y-2 pr-1">
            {sorted.map((u) => {
              const isSelected = u.user_id === selectedUserId;
              return (
                <button
                  key={u.user_id}
                  onClick={() => setSelectedUserId(u.user_id)}
                  className={cn(
                    "w-full text-left card transition-all",
                    isSelected && "ring-2 ring-navy"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-full bg-navy/10 flex-shrink-0 flex items-center justify-center">
                      <IdCard size={16} className="text-navy" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-ink truncate">
                        {u.user_phone || u.user_id.slice(0, 8)}
                      </p>
                      <p className="text-xs text-mist mt-0.5">
                        Submitted {timeAgo(u.uploaded_at)}
                      </p>
                      <div className="flex items-center gap-2 mt-1.5">
                        <ConfidenceBadge value={u.confidence} />
                        <Badge variant="mist">
                          {u.documents.length} doc
                          {u.documents.length === 1 ? "" : "s"}
                        </Badge>
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
          <div className="flex-1 flex flex-col gap-4 overflow-y-auto min-w-0">
            <div className="card">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h2 className="text-base font-bold text-navy font-sora">
                    {selected.user_phone || "Unknown phone"}
                  </h2>
                  <p className="text-xs text-mist mt-0.5 font-mono">
                    {selected.user_id}
                  </p>
                </div>
                <ConfidenceBadge value={selected.confidence} />
              </div>

              {selected.confidence === null && (
                <div className="mb-3 p-3 bg-amber-50 rounded-lg border border-amber-200 flex items-start gap-2">
                  <AlertTriangle
                    size={14}
                    className="text-amber-700 mt-0.5 flex-shrink-0"
                  />
                  <div className="text-xs text-amber-800">
                    <strong>Rekognition was unavailable</strong> when this
                    submission was processed. There is no automated similarity
                    score — judge by visual comparison only.
                  </div>
                </div>
              )}

              {/* Documents */}
              <div className="grid grid-cols-3 gap-3 mt-2">
                {(["id_front", "id_back", "selfie"] as const).map((type) => {
                  const doc = selected.documents.find(
                    (d) => d.document_type === type
                  );
                  return (
                    <KycDocumentCard
                      key={type}
                      label={DOC_LABELS[type]}
                      doc={doc}
                    />
                  );
                })}
              </div>
            </div>

            {/* ── Action buttons ──────────────────────────── */}
            <div className="card">
              <h3 className="text-sm font-bold text-navy mb-3">Decision</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => handleApprove(selected)}
                  className="btn-primary inline-flex items-center gap-1.5"
                >
                  <Check size={14} />
                  Approve KYC
                </button>
                <button
                  onClick={() => setRejectDialogUser(selected)}
                  className="btn-danger inline-flex items-center gap-1.5"
                >
                  <X size={14} />
                  Reject KYC
                </button>
              </div>
              <p className="text-xs text-mist mt-3">
                Approving sets the user&apos;s status to{" "}
                <code className="text-navy">verified</code> and grants the
                identity ATS bonus. Rejecting requires a reason which is sent
                to the user via push and WhatsApp.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-mist">
            Select a submission to review
          </div>
        )}
      </div>

      {/* ── Reject dialog ────────────────────────────────── */}
      {rejectDialogUser && (
        <ActionDialog
          open
          onClose={() => setRejectDialogUser(null)}
          title="Reject KYC submission"
          description={`User ${rejectDialogUser.user_phone || rejectDialogUser.user_id}`}
          confirmLabel="Reject"
          confirmVariant="danger"
          requireReason
          minReasonLength={10}
          onConfirm={async (reason) => {
            await handleReject(rejectDialogUser, reason);
            setRejectDialogUser(null);
          }}
        />
      )}
    </>
  );
}

// ── Sub-components ──────────────────────────────────────────

function ConfidenceBadge({ value }: { value: number | null }) {
  if (value === null) {
    return <Badge variant="amber">No score</Badge>;
  }
  const variant: "ember" | "amber" | "emerald" =
    value >= 85 ? "emerald" : value >= 70 ? "amber" : "ember";
  return <Badge variant={variant}>{value.toFixed(1)}% match</Badge>;
}

function KycDocumentCard({
  label,
  doc,
}: {
  label: string;
  doc: KycQueueItem | undefined;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Reset and refetch whenever the document changes (e.g. user navigates list)
  useEffect(() => {
    setUrl(null);
    setError(null);
    if (!doc) return;

    let cancelled = false;
    setLoading(true);
    kyc
      .documentUrl(doc.id)
      .then((r) => {
        if (!cancelled) setUrl(r.data.url as string);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load document");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [doc]);

  return (
    <div className="space-y-1">
      <div className="aspect-[4/3] bg-sand rounded-lg overflow-hidden border border-sand flex items-center justify-center">
        {!doc ? (
          <div className="text-xs text-mist text-center px-2">
            Missing
            <br />
            document
          </div>
        ) : loading ? (
          <div className="w-full h-full animate-pulse bg-sand" />
        ) : error ? (
          <div className="flex flex-col items-center gap-1 text-mist">
            <ImageIcon size={20} />
            <span className="text-[10px]">Failed</span>
          </div>
        ) : url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt={label}
            className="w-full h-full object-cover cursor-zoom-in"
            onClick={() => window.open(url, "_blank", "noopener")}
          />
        ) : (
          <ImageIcon size={20} className="text-mist" />
        )}
      </div>
      <p className="text-[11px] text-mist uppercase tracking-wider text-center">
        {label}
      </p>
    </div>
  );
}

function KycSkeleton() {
  return (
    <div className="flex gap-6">
      <div className="w-[380px] space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card animate-pulse">
            <div className="flex gap-3">
              <div className="w-10 h-10 bg-sand rounded-full" />
              <div className="flex-1 space-y-2">
                <div className="h-3 bg-sand rounded w-2/3" />
                <div className="h-2.5 bg-sand rounded w-1/2" />
                <div className="h-2 bg-sand rounded w-1/3" />
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="flex-1 card animate-pulse">
        <div className="h-4 bg-sand rounded w-1/3 mb-4" />
        <div className="grid grid-cols-3 gap-3">
          <div className="aspect-[4/3] bg-sand rounded-lg" />
          <div className="aspect-[4/3] bg-sand rounded-lg" />
          <div className="aspect-[4/3] bg-sand rounded-lg" />
        </div>
      </div>
    </div>
  );
}
