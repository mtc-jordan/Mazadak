"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  Briefcase,
  Lock,
  Download,
  Award,
  UserPlus,
  X as XIcon,
  Check,
  TrendingUp,
} from "lucide-react";
import { tenders } from "@/lib/api";
import type {
  B2BRoomDetail,
  B2BBidItem,
  B2BAnalytics,
} from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/badge";
import { cn } from "@/lib/utils";

type Tab = "overview" | "bids" | "invitations" | "analytics";

export default function TenderDetailPage() {
  const params = useParams<{ id: string }>();
  const roomId = params.id;

  const [tab, setTab] = useState<Tab>("overview");

  const {
    data: room,
    loading,
    refetch,
  } = useAsync<B2BRoomDetail>(
    () => tenders.get(roomId).then((r) => r.data),
    [roomId]
  );

  if (loading) {
    return <div className="card animate-pulse h-40" />;
  }

  if (!room) {
    return <div className="text-sm text-mist">Tender room not found.</div>;
  }

  const canAnnounce =
    (room.status === "open" || room.status === "closed") &&
    room.bids.length > 0;

  return (
    <>
      <Link
        href="/admin/tenders"
        className="inline-flex items-center gap-1 text-sm text-mist hover:text-navy mb-4"
      >
        <ArrowLeft size={14} />
        Back to tenders
      </Link>

      {/* Header */}
      <div className="card mb-4">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-lg bg-navy/10 flex items-center justify-center flex-shrink-0">
              <Briefcase size={22} className="text-navy" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold text-navy font-sora">
                  {room.client_name}
                </h1>
                {room.sealed && <Lock size={14} className="text-navy/60" />}
              </div>
              {room.client_name_ar && (
                <p className="text-sm text-mist" dir="rtl">
                  {room.client_name_ar}
                </p>
              )}
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs font-mono text-mist">
                  {room.tender_reference}
                </span>
                <Badge
                  variant={
                    room.status === "results_announced"
                      ? "gold"
                      : room.status === "open"
                        ? "emerald"
                        : "mist"
                  }
                >
                  {room.status.replace("_", " ")}
                </Badge>
              </div>
            </div>
          </div>

          <div className="flex gap-2">
            <button
              onClick={() =>
                exportBlob(
                  tenders.exportCompliancePdf(room.id),
                  `tender_${room.tender_reference}_compliance.pdf`
                )
              }
              className="btn-outline inline-flex items-center gap-1.5 text-xs"
            >
              <Download size={13} />
              Compliance PDF
            </button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b border-sand">
        {(
          ["overview", "bids", "invitations", "analytics"] as Tab[]
        ).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px capitalize transition-colors",
              tab === t
                ? "border-navy text-navy"
                : "border-transparent text-mist hover:text-ink"
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && <OverviewTab room={room} />}
      {tab === "bids" && (
        <BidsTab room={room} canAnnounce={canAnnounce} refetch={refetch} />
      )}
      {tab === "invitations" && <InvitationsTab room={room} refetch={refetch} />}
      {tab === "analytics" && <AnalyticsTab roomId={room.id} />}
    </>
  );
}

// ─── Overview ────────────────────────────────────────────────

function OverviewTab({ room }: { room: B2BRoomDetail }) {
  const jod = (cents: number | null | undefined) =>
    cents ? `${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })} JOD` : "—";

  return (
    <div className="grid grid-cols-2 gap-4">
      <InfoCard label="Submission Deadline" value={new Date(room.submission_deadline).toLocaleString()} />
      <InfoCard
        label="Results Announced"
        value={
          room.results_announced_at
            ? new Date(room.results_announced_at).toLocaleString()
            : "Not announced"
        }
      />
      <InfoCard label="Min Lot Amount" value={jod(room.min_lot_amount)} />
      <InfoCard label="Estimated Value" value={jod(room.estimated_value)} />
      <InfoCard label="Sealed Bidding" value={room.sealed ? "Yes" : "No"} />
      <InfoCard label="Created" value={new Date(room.created_at).toLocaleDateString()} />
      {room.description && (
        <div className="col-span-2 card">
          <div className="text-[11px] text-mist uppercase tracking-wider mb-1">
            Description
          </div>
          <p className="text-sm text-ink whitespace-pre-wrap">
            {room.description}
          </p>
        </div>
      )}
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="text-[11px] text-mist uppercase tracking-wider">
        {label}
      </div>
      <div className="text-sm font-medium text-ink mt-1">{value}</div>
    </div>
  );
}

// ─── Bids ────────────────────────────────────────────────────

function BidsTab({
  room,
  canAnnounce,
  refetch,
}: {
  room: B2BRoomDetail;
  canAnnounce: boolean;
  refetch: () => void;
}) {
  const [announcing, setAnnouncing] = useState<string | null>(null);
  const bids = [...room.bids].sort((a, b) => b.amount - a.amount);
  const amountsVisible =
    !room.sealed || room.status === "results_announced";

  const announce = async (bidId: string) => {
    if (!confirm("Announce this bid as the winner?")) return;
    setAnnouncing(bidId);
    try {
      await tenders.announce(room.id, bidId);
      refetch();
    } finally {
      setAnnouncing(null);
    }
  };

  if (bids.length === 0) {
    return (
      <div className="card text-center text-sm text-mist py-8">
        No bids submitted yet.
      </div>
    );
  }

  return (
    <div className="card">
      {room.sealed && !amountsVisible && (
        <div className="mb-3 p-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800 flex items-center gap-2">
          <Lock size={12} />
          Sealed bid mode — amounts are visible only to admins. Bidders see
          results after announcement.
        </div>
      )}

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] text-mist uppercase tracking-wider border-b border-sand">
            <th className="pb-2 pr-2">Rank</th>
            <th className="pb-2 pr-2">Bidder</th>
            <th className="pb-2 pr-2">Submission Ref</th>
            <th className="pb-2 pr-2 text-right">Amount</th>
            <th className="pb-2 pr-2 text-right">Validity</th>
            <th className="pb-2 pr-2">Submitted</th>
            <th className="pb-2 pr-2"></th>
          </tr>
        </thead>
        <tbody>
          {bids.map((bid, i) => (
            <tr
              key={bid.id}
              className={cn(
                "border-b border-sand/50",
                bid.is_winner && "bg-gold/10"
              )}
            >
              <td className="py-2 pr-2 font-mono text-xs">
                {i + 1}
                {bid.is_winner && " ★"}
              </td>
              <td className="py-2 pr-2">
                {bid.bidder_name ?? bid.bidder_id.slice(0, 8)}
              </td>
              <td className="py-2 pr-2 font-mono text-xs text-mist">
                {bid.submission_ref ?? "—"}
              </td>
              <td className="py-2 pr-2 text-right font-mono">
                {(bid.amount / 100).toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                })}{" "}
                JOD
              </td>
              <td className="py-2 pr-2 text-right">{bid.validity_days}d</td>
              <td className="py-2 pr-2 text-xs text-mist">
                {new Date(bid.submitted_at).toLocaleString()}
              </td>
              <td className="py-2 pr-2 text-right">
                {bid.is_winner ? (
                  <Badge variant="gold">Winner</Badge>
                ) : canAnnounce ? (
                  <button
                    onClick={() => announce(bid.id)}
                    disabled={announcing === bid.id}
                    className="btn-outline text-xs inline-flex items-center gap-1 py-1 px-2"
                  >
                    <Award size={11} />
                    Announce
                  </button>
                ) : room.status === "results_announced" ? (
                  <button
                    onClick={() =>
                      exportBlob(
                        tenders.exportAwardLetter(room.id, bid.id),
                        `award_${bid.id.slice(0, 8)}.pdf`
                      )
                    }
                    className="btn-outline text-xs inline-flex items-center gap-1 py-1 px-2"
                  >
                    <Download size={11} />
                    Letter
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Invitations ─────────────────────────────────────────────

function InvitationsTab({
  room,
  refetch,
}: {
  room: B2BRoomDetail;
  refetch: () => void;
}) {
  const [userId, setUserId] = useState("");
  const [minAts, setMinAts] = useState<string>("");
  const [minKyc, setMinKyc] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await tenders.invite(room.id, {
        invitations: [
          {
            user_id: userId,
            min_ats_score: minAts ? Number(minAts) : null,
            min_kyc_level: minKyc || null,
          },
        ],
      });
      setUserId("");
      setMinAts("");
      setMinKyc("");
      refetch();
    } finally {
      setSubmitting(false);
    }
  };

  const revoke = async (invitationId: string) => {
    if (!confirm("Revoke this invitation?")) return;
    await tenders.revokeInvitation(room.id, invitationId);
    refetch();
  };

  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="text-sm font-bold text-navy mb-3 flex items-center gap-2">
          <UserPlus size={14} />
          Invite Bidder
        </h3>
        <form onSubmit={invite} className="grid grid-cols-4 gap-2 items-end">
          <div className="col-span-2">
            <label className="block text-[11px] text-mist mb-1">User ID</label>
            <input
              required
              className="input font-mono text-xs"
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              placeholder="uuid"
            />
          </div>
          <div>
            <label className="block text-[11px] text-mist mb-1">Min ATS</label>
            <input
              type="number"
              className="input"
              value={minAts}
              onChange={(e) => setMinAts(e.target.value)}
              placeholder="—"
            />
          </div>
          <div>
            <label className="block text-[11px] text-mist mb-1">Min KYC</label>
            <select
              className="input"
              value={minKyc}
              onChange={(e) => setMinKyc(e.target.value)}
            >
              <option value="">—</option>
              <option value="verified">Verified</option>
            </select>
          </div>
          <div className="col-span-4">
            <button
              type="submit"
              disabled={submitting}
              className="btn-primary w-full"
            >
              {submitting ? "Inviting..." : "Send Invitation"}
            </button>
          </div>
        </form>
      </div>

      <div className="card">
        <h3 className="text-sm font-bold text-navy mb-3">
          Invitations ({room.invitations.length})
        </h3>
        {room.invitations.length === 0 ? (
          <p className="text-sm text-mist">No invitations yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] text-mist uppercase tracking-wider border-b border-sand">
                <th className="pb-2 pr-2">Bidder</th>
                <th className="pb-2 pr-2">Status</th>
                <th className="pb-2 pr-2">Min ATS</th>
                <th className="pb-2 pr-2">Min KYC</th>
                <th className="pb-2 pr-2">Invited</th>
                <th className="pb-2 pr-2"></th>
              </tr>
            </thead>
            <tbody>
              {room.invitations.map((inv) => (
                <tr key={inv.id} className="border-b border-sand/50">
                  <td className="py-2 pr-2">
                    {inv.user_name ?? inv.user_id.slice(0, 8)}
                  </td>
                  <td className="py-2 pr-2">
                    <Badge
                      variant={
                        inv.status === "accepted"
                          ? "emerald"
                          : inv.status === "revoked"
                            ? "ember"
                            : "mist"
                      }
                    >
                      {inv.status}
                    </Badge>
                  </td>
                  <td className="py-2 pr-2 font-mono text-xs">
                    {inv.min_ats_score ?? "—"}
                  </td>
                  <td className="py-2 pr-2 text-xs">
                    {inv.min_kyc_level ?? "—"}
                  </td>
                  <td className="py-2 pr-2 text-xs text-mist">
                    {new Date(inv.invited_at).toLocaleDateString()}
                  </td>
                  <td className="py-2 pr-2 text-right">
                    {inv.status !== "revoked" && (
                      <button
                        onClick={() => revoke(inv.id)}
                        className="text-ember hover:bg-ember/10 p-1 rounded"
                        aria-label="Revoke"
                      >
                        <XIcon size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ─── Analytics ───────────────────────────────────────────────

function AnalyticsTab({ roomId }: { roomId: string }) {
  const { data, loading } = useAsync<B2BAnalytics>(
    () => tenders.analytics(roomId).then((r) => r.data),
    [roomId]
  );

  if (loading) return <div className="card animate-pulse h-40" />;
  if (!data) return <div className="card text-sm text-mist">No data</div>;

  const jod = (cents: number | null | undefined) =>
    cents ? `${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })} JOD` : "—";

  return (
    <div className="grid grid-cols-3 gap-4">
      <StatCard
        label="Participation Rate"
        value={`${(data.participation_rate * 100).toFixed(1)}%`}
        sub={`${data.bid_count} of ${data.invited_count} invited`}
      />
      <StatCard
        label="Average Bid"
        value={jod(data.avg_bid_amount)}
      />
      <StatCard
        label="Winning Amount"
        value={jod(data.winner_amount)}
      />
      <StatCard label="Min Bid" value={jod(data.min_bid_amount)} />
      <StatCard label="Max Bid" value={jod(data.max_bid_amount)} />
      <StatCard
        label="Price vs Estimate"
        value={
          data.price_vs_estimate_ratio !== null &&
          data.price_vs_estimate_ratio !== undefined
            ? `${(data.price_vs_estimate_ratio * 100).toFixed(1)}%`
            : "—"
        }
      />
      <StatCard
        label="Time to Close"
        value={
          data.time_to_close_hours !== null &&
          data.time_to_close_hours !== undefined
            ? `${data.time_to_close_hours.toFixed(1)} h`
            : "—"
        }
      />
      <StatCard label="Total Bids" value={String(data.bid_count)} />
      <StatCard label="Invited" value={String(data.invited_count)} />
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="card">
      <div className="text-[11px] text-mist uppercase tracking-wider">
        {label}
      </div>
      <div className="text-xl font-bold text-navy font-sora mt-1">{value}</div>
      {sub && <div className="text-[11px] text-mist mt-1">{sub}</div>}
    </div>
  );
}

// ─── Utils ───────────────────────────────────────────────────

async function exportBlob(
  promise: Promise<{ data: Blob }>,
  filename: string
) {
  try {
    const res = await promise;
    const url = URL.createObjectURL(res.data);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    console.error("Export failed", e);
  }
}
