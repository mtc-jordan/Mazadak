"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import {
  Briefcase,
  Plus,
  Upload,
  ChevronRight,
  Lock,
  Users,
  FileText,
} from "lucide-react";
import { tenders } from "@/lib/api";
import type {
  B2BRoomListItem,
  B2BRoomListResponse,
  B2BRoomStatus,
} from "@/lib/types";
import { useAsync } from "@/hooks/use-async";
import { Badge } from "@/components/badge";
import { EmptyState } from "@/components/empty-state";
import { cn } from "@/lib/utils";

// ═══════════════════════════════════════════════════════════════
// B2B Tender Rooms — Admin List
// ═══════════════════════════════════════════════════════════════

const STATUS_TABS: Array<{ key: B2BRoomStatus | "all"; label: string }> = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "closed", label: "Closed" },
  { key: "results_announced", label: "Announced" },
  { key: "cancelled", label: "Cancelled" },
];

export default function TendersPage() {
  const [statusFilter, setStatusFilter] = useState<B2BRoomStatus | "all">("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const { data, loading, refetch } = useAsync<B2BRoomListResponse>(
    () =>
      tenders
        .list(statusFilter === "all" ? {} : { status: statusFilter })
        .then((r) => r.data),
    [statusFilter]
  );

  const items = data?.items ?? [];

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-navy font-sora">
            B2B Tender Rooms
          </h1>
          <p className="text-sm text-mist mt-1">
            Private institutional auctions with sealed bidding
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setImportOpen(true)}
            className="btn-outline inline-flex items-center gap-1.5"
          >
            <Upload size={14} />
            Import CSV
          </button>
          <button
            onClick={() => setCreateOpen(true)}
            className="btn-primary inline-flex items-center gap-1.5"
          >
            <Plus size={14} />
            New Tender
          </button>
        </div>
      </div>

      {/* Status tabs */}
      <div className="flex gap-1 mb-4 border-b border-sand">
        {STATUS_TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setStatusFilter(t.key)}
            className={cn(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              statusFilter === t.key
                ? "border-navy text-navy"
                : "border-transparent text-mist hover:text-ink"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* List */}
      {loading ? (
        <TenderListSkeleton />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="No tender rooms"
          description="Create your first B2B tender room to get started."
        />
      ) : (
        <div className="space-y-2">
          {items.map((room) => (
            <TenderRow key={room.id} room={room} />
          ))}
        </div>
      )}

      {/* Dialogs */}
      {createOpen && (
        <CreateTenderDialog
          onClose={() => setCreateOpen(false)}
          onCreated={() => {
            setCreateOpen(false);
            refetch();
          }}
        />
      )}
      {importOpen && (
        <ImportCsvDialog
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setImportOpen(false);
            refetch();
          }}
        />
      )}
    </>
  );
}

// ─── Row ─────────────────────────────────────────────────────

function TenderRow({ room }: { room: B2BRoomListItem }) {
  const statusVariant = useMemo(() => {
    switch (room.status) {
      case "open":
        return "emerald";
      case "results_announced":
        return "gold";
      case "cancelled":
        return "ember";
      default:
        return "mist";
    }
  }, [room.status]);

  const jod = (cents: number | null | undefined) =>
    cents ? `${(cents / 100).toLocaleString()} JOD` : "—";

  const deadline = new Date(room.submission_deadline);
  const isPast = deadline.getTime() < Date.now();

  return (
    <Link
      href={`/admin/tenders/${room.id}`}
      className="card hover:ring-1 hover:ring-navy/30 transition-all block"
    >
      <div className="flex items-center gap-4">
        <div className="w-10 h-10 rounded-lg bg-navy/10 flex items-center justify-center flex-shrink-0">
          <Briefcase size={18} className="text-navy" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-ink truncate">
              {room.client_name}
            </span>
            {room.sealed && (
              <Lock size={12} className="text-navy/60" aria-label="Sealed" />
            )}
            <Badge variant={statusVariant}>
              {room.status.replace("_", " ")}
            </Badge>
          </div>
          <div className="flex items-center gap-3 text-xs text-mist mt-1">
            <span className="font-mono">{room.tender_reference}</span>
            <span className="flex items-center gap-1">
              <Users size={11} />
              {room.invitation_count} invited
            </span>
            <span className="flex items-center gap-1">
              <FileText size={11} />
              {room.bid_count} bids
            </span>
            <span>Min {jod(room.min_lot_amount)}</span>
          </div>
        </div>

        <div className="text-right flex-shrink-0">
          <div className="text-xs text-mist">Deadline</div>
          <div
            className={cn(
              "text-xs font-medium",
              isPast ? "text-ember" : "text-ink"
            )}
          >
            {deadline.toLocaleDateString()}
          </div>
        </div>

        <ChevronRight size={16} className="text-mist flex-shrink-0" />
      </div>
    </Link>
  );
}

// ─── Create dialog ────────────────────────────────────────────

function CreateTenderDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const [form, setForm] = useState({
    client_name: "",
    client_name_ar: "",
    tender_reference: "",
    description: "",
    submission_deadline: "",
    sealed: true,
    min_lot_amount: 1_000_000,
    estimated_value: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await tenders.create({
        client_name: form.client_name,
        client_name_ar: form.client_name_ar || null,
        tender_reference: form.tender_reference,
        description: form.description || null,
        submission_deadline: new Date(form.submission_deadline).toISOString(),
        sealed: form.sealed,
        min_lot_amount: form.min_lot_amount,
        estimated_value: form.estimated_value ? Number(form.estimated_value) : null,
      });
      onCreated();
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message_en ?? "Failed to create");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl max-w-lg w-full max-h-[90vh] overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-navy font-sora mb-4">
          Create Tender Room
        </h2>

        <form onSubmit={submit} className="space-y-3">
          <Field label="Client Name">
            <input
              required
              className="input"
              value={form.client_name}
              onChange={(e) =>
                setForm({ ...form, client_name: e.target.value })
              }
            />
          </Field>

          <Field label="Client Name (Arabic)">
            <input
              className="input"
              dir="rtl"
              value={form.client_name_ar}
              onChange={(e) =>
                setForm({ ...form, client_name_ar: e.target.value })
              }
            />
          </Field>

          <Field label="Tender Reference">
            <input
              required
              className="input font-mono"
              placeholder="T-2026-001"
              value={form.tender_reference}
              onChange={(e) =>
                setForm({ ...form, tender_reference: e.target.value })
              }
            />
          </Field>

          <Field label="Submission Deadline">
            <input
              required
              type="datetime-local"
              className="input"
              value={form.submission_deadline}
              onChange={(e) =>
                setForm({ ...form, submission_deadline: e.target.value })
              }
            />
          </Field>

          <Field label="Minimum Lot Amount (cents)">
            <input
              required
              type="number"
              min={1_000_000}
              step={100}
              className="input font-mono"
              value={form.min_lot_amount}
              onChange={(e) =>
                setForm({
                  ...form,
                  min_lot_amount: Number(e.target.value),
                })
              }
            />
            <p className="text-[11px] text-mist mt-1">
              Minimum 10,000 JOD (1,000,000 cents) per FR-B2B-002
            </p>
          </Field>

          <Field label="Estimated Value (cents, optional)">
            <input
              type="number"
              className="input font-mono"
              value={form.estimated_value}
              onChange={(e) =>
                setForm({ ...form, estimated_value: e.target.value })
              }
            />
          </Field>

          <Field label="Description">
            <textarea
              className="input h-20"
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
            />
          </Field>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.sealed}
              onChange={(e) => setForm({ ...form, sealed: e.target.checked })}
            />
            Sealed bid mode (amounts hidden until results announced)
          </label>

          {error && (
            <div className="text-sm text-ember bg-ember/10 p-2 rounded">
              {error}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="btn-outline"
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={submitting}
            >
              {submitting ? "Creating..." : "Create Room"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Import CSV dialog ───────────────────────────────────────

function ImportCsvDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{
    created_count: number;
    errors: string[];
  } | null>(null);

  const submit = async () => {
    if (!file) return;
    setSubmitting(true);
    try {
      const res = await tenders.importCsv(file);
      setResult(res.data);
      if (res.data.created_count > 0) {
        setTimeout(onImported, 1500);
      }
    } catch {
      setResult({ created_count: 0, errors: ["Upload failed"] });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl max-w-md w-full p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold text-navy font-sora mb-2">
          Import Tenders from CSV
        </h2>
        <p className="text-xs text-mist mb-4">
          Columns: tender_reference, client_name, submission_deadline,
          min_lot_amount, estimated_value, description, sealed
        </p>

        <input
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="w-full text-sm mb-4"
        />

        {result && (
          <div className="mb-4 space-y-2">
            <div className="text-sm">
              Created:{" "}
              <span className="font-bold text-emerald-600">
                {result.created_count}
              </span>
            </div>
            {result.errors.length > 0 && (
              <div className="text-xs text-ember space-y-1 max-h-32 overflow-y-auto">
                {result.errors.map((e, i) => (
                  <div key={i}>• {e}</div>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="btn-outline"
            disabled={submitting}
          >
            Close
          </button>
          <button
            onClick={submit}
            disabled={!file || submitting}
            className="btn-primary"
          >
            {submitting ? "Uploading..." : "Upload"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-mist uppercase tracking-wider mb-1">
        {label}
      </label>
      {children}
    </div>
  );
}

function TenderListSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="card animate-pulse">
          <div className="flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-sand" />
            <div className="flex-1 space-y-2">
              <div className="h-3 bg-sand rounded w-1/2" />
              <div className="h-2 bg-sand rounded w-1/3" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
