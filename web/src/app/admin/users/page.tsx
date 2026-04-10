"use client";

import { useState, useCallback, useRef } from "react";
import {
  Users,
  Search,
  ShieldAlert,
  ShieldOff,
  ShieldBan,
  ShieldCheck,
  Phone,
  Mail,
  CalendarDays,
  Activity,
  ChevronDown,
  AlertTriangle,
} from "lucide-react";
import { users as usersApi } from "@/lib/api";
import { withAuditLog } from "@/lib/audit";
import type { User, AtsComponent, Strike, AdminAction } from "@/lib/types";
import { cn, maskPhone, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/badge";
import { SearchInput } from "@/components/search-input";
import { ActionDialog } from "@/components/action-dialog";
import { EmptyState } from "@/components/empty-state";

// ═══════════════════════════════════════════════════════════════
// User Management
// ═══════════════════════════════════════════════════════════════

export default function UsersPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<User[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [userLoading, setUserLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Dialog
  const [dialog, setDialog] = useState<{
    action: "warn" | "suspend" | "ban" | "restore";
    user: User;
  } | null>(null);

  const handleSearch = useCallback((q: string) => {
    setQuery(q);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!q.trim()) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const resp = await usersApi.search(q);
        setResults(resp.data.users as User[]);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
  }, []);

  const selectUser = useCallback(async (userId: string) => {
    setUserLoading(true);
    try {
      const resp = await usersApi.get(userId);
      setSelectedUser(resp.data as User);
    } catch {
      setSelectedUser(null);
    } finally {
      setUserLoading(false);
    }
  }, []);

  const handleAction = async (
    action: "warn" | "suspend" | "ban" | "restore",
    user: User,
    reason: string
  ) => {
    const actionMap: Record<string, AdminAction> = {
      warn: "warn",
      suspend: "suspend",
      ban: "ban",
      restore: "restore",
    };
    await withAuditLog(
      {
        action: actionMap[action] as AdminAction,
        targetType: "user",
        targetId: user.id,
        reason,
      },
      () => usersApi[action](user.id, reason)
    );
    // Reload user
    await selectUser(user.id);
  };

  return (
    <>
      <div className="flex gap-6 h-[calc(100vh-8rem)]">
        {/* ── Search panel ─────────────────────────────────── */}
        <div className="w-[380px] flex-shrink-0 flex flex-col">
          <h1 className="text-lg font-bold text-navy font-sora mb-4">
            User Management
          </h1>

          <SearchInput
            value={query}
            onChange={handleSearch}
            placeholder="Search by phone, name, or ID..."
          />

          <div className="flex-1 overflow-y-auto mt-3 space-y-1.5">
            {searching && (
              <div className="text-center py-8 text-sm text-mist">
                Searching...
              </div>
            )}

            {!searching && query && results.length === 0 && (
              <EmptyState
                icon={Users}
                title="No users found"
                description={`No results for "${query}"`}
              />
            )}

            {!searching && !query && (
              <div className="text-center py-12 text-sm text-mist">
                <Search size={20} className="mx-auto mb-2 text-sand" />
                Search by phone number or name
              </div>
            )}

            {results.map((user) => (
              <button
                key={user.id}
                onClick={() => selectUser(user.id)}
                className={cn(
                  "w-full text-left card transition-all",
                  selectedUser?.id === user.id && "ring-2 ring-navy"
                )}
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-navy/10 flex items-center justify-center flex-shrink-0">
                    <span className="text-sm font-bold text-navy">
                      {user.full_name_ar?.charAt(0) ?? "?"}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-ink truncate">
                      {user.full_name_ar}
                    </p>
                    <p className="text-xs text-mist">{maskPhone(user.phone)}</p>
                  </div>
                  <UserStatusBadge status={user.status} />
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* ── Detail panel ─────────────────────────────────── */}
        {userLoading ? (
          <div className="flex-1 card animate-pulse space-y-4">
            <div className="h-5 bg-sand rounded w-1/3" />
            <div className="h-3 bg-sand rounded w-1/4" />
            <div className="h-40 bg-sand rounded" />
          </div>
        ) : selectedUser ? (
          <UserDetail
            user={selectedUser}
            onAction={(action) =>
              setDialog({ action, user: selectedUser })
            }
          />
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-mist">
            Search and select a user to view details
          </div>
        )}
      </div>

      {/* ── Action dialog ──────────────────────────────────── */}
      {dialog && (
        <ActionDialog
          open
          onClose={() => setDialog(null)}
          title={`${dialog.action.charAt(0).toUpperCase() + dialog.action.slice(1)} User`}
          description={`${dialog.user.full_name_ar} (${maskPhone(dialog.user.phone)})`}
          confirmLabel={
            dialog.action.charAt(0).toUpperCase() + dialog.action.slice(1)
          }
          confirmVariant={
            dialog.action === "ban" || dialog.action === "suspend"
              ? "danger"
              : dialog.action === "restore"
                ? "primary"
                : "gold"
          }
          onConfirm={(reason) =>
            handleAction(dialog.action, dialog.user, reason)
          }
        />
      )}
    </>
  );
}

// ═══════════════════════════════════════════════════════════════
// User Detail
// ═══════════════════════════════════════════════════════════════

function UserDetail({
  user,
  onAction,
}: {
  user: User;
  onAction: (action: "warn" | "suspend" | "ban" | "restore") => void;
}) {
  const [showStrikes, setShowStrikes] = useState(false);

  return (
    <div className="flex-1 overflow-y-auto space-y-4">
      {/* Profile header */}
      <div className="card">
        <div className="flex items-start gap-4">
          <div className="w-14 h-14 rounded-full bg-navy/10 flex items-center justify-center flex-shrink-0">
            <span className="text-xl font-bold text-navy font-sora">
              {user.full_name_ar?.charAt(0) ?? "?"}
            </span>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-navy font-sora">
                {user.full_name_ar}
              </h2>
              <UserStatusBadge status={user.status} />
              <KycBadge status={user.kyc_status} />
            </div>
            {user.full_name_en && (
              <p className="text-sm text-mist">{user.full_name_en}</p>
            )}
            <div className="flex items-center gap-4 mt-2 text-xs text-mist">
              <span className="flex items-center gap-1">
                <Phone size={12} /> {user.phone}
              </span>
              {user.email && (
                <span className="flex items-center gap-1">
                  <Mail size={12} /> {user.email}
                </span>
              )}
              <span className="flex items-center gap-1">
                <CalendarDays size={12} /> Joined{" "}
                {timeAgo(user.member_since)}
              </span>
              <span className="flex items-center gap-1">
                <Activity size={12} /> Active{" "}
                {timeAgo(user.last_active)}
              </span>
            </div>
          </div>
        </div>

        {/* Quick stats */}
        <div className="grid grid-cols-5 gap-3 mt-4 pt-4 border-t border-sand">
          <StatBox label="Role" value={user.role} />
          <StatBox label="Listings" value={user.total_listings} />
          <StatBox label="Bids" value={user.total_bids} />
          <StatBox label="Sales" value={user.total_sales} />
          <StatBox label="Disputes" value={user.dispute_count} />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* ATS Breakdown */}
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold text-navy">ATS Breakdown</h3>
            <div className="flex items-center gap-2">
              <TierBadge tier={user.ats_tier} />
              <span className="text-lg font-bold text-navy font-mono">
                {user.ats_score}
              </span>
            </div>
          </div>
          <div className="space-y-2.5">
            {user.ats_components.map((c) => (
              <AtsBar key={c.key} component={c} />
            ))}
            {user.ats_components.length === 0 && (
              <p className="text-xs text-mist">No ATS data available</p>
            )}
          </div>
        </div>

        {/* Actions + Strikes */}
        <div className="space-y-4">
          {/* Admin actions */}
          <div className="card">
            <h3 className="text-sm font-bold text-navy mb-3">Admin Actions</h3>
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => onAction("warn")}
                className="btn-outline inline-flex items-center justify-center gap-1.5 text-amber-600 border-amber-300 hover:bg-amber-50"
              >
                <ShieldAlert size={14} />
                Warn
              </button>
              <button
                onClick={() => onAction("suspend")}
                className="btn-outline inline-flex items-center justify-center gap-1.5 text-ember border-ember/30 hover:bg-ember/5"
              >
                <ShieldOff size={14} />
                Suspend
              </button>
              <button
                onClick={() => onAction("ban")}
                className="btn-danger inline-flex items-center justify-center gap-1.5"
              >
                <ShieldBan size={14} />
                Ban
              </button>
              <button
                onClick={() => onAction("restore")}
                disabled={user.status === "active"}
                className={cn(
                  "btn-primary inline-flex items-center justify-center gap-1.5",
                  user.status === "active" && "opacity-30 cursor-not-allowed"
                )}
              >
                <ShieldCheck size={14} />
                Restore
              </button>
            </div>
          </div>

          {/* Strike history */}
          <div className="card">
            <button
              onClick={() => setShowStrikes(!showStrikes)}
              className="w-full flex items-center justify-between"
            >
              <h3 className="text-sm font-bold text-navy flex items-center gap-2">
                <AlertTriangle size={14} />
                Strike History ({user.strikes.length})
              </h3>
              <ChevronDown
                size={14}
                className={cn(
                  "text-mist transition-transform",
                  showStrikes && "rotate-180"
                )}
              />
            </button>

            {showStrikes && (
              <div className="mt-3 space-y-2">
                {user.strikes.length === 0 ? (
                  <p className="text-xs text-mist">Clean record</p>
                ) : (
                  user.strikes.map((s) => (
                    <StrikeRow key={s.id} strike={s} />
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────

function StatBox({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="text-center">
      <p className="text-lg font-bold text-navy font-sora">{value}</p>
      <p className="text-[10px] text-mist uppercase tracking-wider">
        {label}
      </p>
    </div>
  );
}

function AtsBar({ component }: { component: AtsComponent }) {
  const pct = Math.round(component.value * 100);
  const barColor =
    pct >= 80 ? "bg-emerald" : pct >= 50 ? "bg-gold" : "bg-ember";

  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-ink font-medium">{component.label}</span>
        <span className="text-mist font-mono">
          {component.earned_points}/{component.max_points}
        </span>
      </div>
      <div className="h-1.5 bg-sand rounded-full overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function StrikeRow({ strike }: { strike: Strike }) {
  return (
    <div
      className={cn(
        "p-2.5 rounded-lg border text-xs",
        strike.is_active
          ? "border-ember/20 bg-ember/5"
          : "border-sand bg-fog"
      )}
    >
      <div className="flex items-center justify-between">
        <span className="font-semibold text-ink">{strike.type}</span>
        <Badge variant={strike.is_active ? "ember" : "mist"}>
          {strike.is_active ? "Active" : "Expired"}
        </Badge>
      </div>
      <p className="text-mist mt-1">{strike.reason}</p>
      <p className="text-mist mt-1">
        Issued {timeAgo(strike.issued_at)} by {strike.issued_by}
        {strike.expires_at && ` · Expires ${timeAgo(strike.expires_at)}`}
      </p>
    </div>
  );
}

function UserStatusBadge({ status }: { status: string }) {
  const variant = {
    active: "emerald",
    warned: "amber",
    suspended: "ember",
    banned: "ember",
  } as const;
  return (
    <Badge variant={variant[status as keyof typeof variant] ?? "mist"}>
      {status}
    </Badge>
  );
}

function KycBadge({ status }: { status: string }) {
  if (status === "verified")
    return <Badge variant="emerald">KYC Verified</Badge>;
  if (status === "pending")
    return <Badge variant="amber">KYC Pending</Badge>;
  if (status === "rejected")
    return <Badge variant="ember">KYC Rejected</Badge>;
  return null;
}

function TierBadge({ tier }: { tier: string }) {
  const color = {
    elite: "emerald",
    pro: "gold",
    trusted: "navy",
    starter: "mist",
  } as const;
  return (
    <Badge variant={color[tier as keyof typeof color] ?? "mist"}>
      {tier.toUpperCase()}
    </Badge>
  );
}
