"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { AuthGuard, useAuth } from "@/lib/auth";
import {
  Shield,
  Scale,
  Users,
  LayoutDashboard,
  LogOut,
  ChevronRight,
  Briefcase,
} from "lucide-react";

const NAV_ITEMS = [
  {
    href: "/admin",
    label: "Dashboard",
    icon: LayoutDashboard,
  },
  {
    href: "/admin/moderation",
    label: "Moderation",
    icon: Shield,
  },
  {
    href: "/admin/disputes",
    label: "Disputes",
    icon: Scale,
  },
  {
    href: "/admin/users",
    label: "Users",
    icon: Users,
  },
  {
    href: "/admin/tenders",
    label: "B2B Tenders",
    icon: Briefcase,
  },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <AuthGuard>
    <div className="flex h-screen overflow-hidden">
      {/* ── Sidebar ─────────────────────────────────────────── */}
      <aside className="w-60 flex-shrink-0 bg-navy-dark flex flex-col">
        {/* Brand */}
        <div className="h-16 flex items-center gap-2 px-5 border-b border-white/10">
          <span className="text-2xl font-extrabold text-gold font-sora">
            م
          </span>
          <div className="leading-tight">
            <span className="text-white font-sora font-bold text-sm tracking-wide">
              MZADAK
            </span>
            <span className="block text-white/40 text-[10px] font-medium tracking-widest">
              ADMIN
            </span>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === "/admin"
                ? pathname === "/admin"
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "bg-white/10 text-white"
                    : "text-white/50 hover:text-white/80 hover:bg-white/5"
                )}
              >
                <Icon size={18} />
                {item.label}
                {isActive && (
                  <ChevronRight size={14} className="ml-auto opacity-60" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="p-3 border-t border-white/10">
          {user && (
            <div className="px-3 py-2 mb-1 text-xs text-white/50 truncate">
              {user.name}
              <span className="ml-1 text-white/30">({user.role})</span>
            </div>
          )}
          <button
            onClick={() => logout()}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm text-white/40 hover:text-white/80 hover:bg-white/5 transition-colors"
          >
            <LogOut size={18} />
            Sign out
          </button>
        </div>
      </aside>

      {/* ── Main content ────────────────────────────────────── */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="h-16 flex-shrink-0 bg-white border-b border-sand flex items-center justify-between px-6">
          <div className="text-sm text-mist">
            {NAV_ITEMS.find(
              (n) =>
                n.href === "/admin"
                  ? pathname === "/admin"
                  : pathname.startsWith(n.href)
            )?.label ?? "Admin"}
          </div>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-navy/10 flex items-center justify-center">
              <span className="text-xs font-bold text-navy">
                {user?.name?.charAt(0)?.toUpperCase() ?? "A"}
              </span>
            </div>
          </div>
        </header>

        {/* Page content */}
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
      </main>
    </div>
    </AuthGuard>
  );
}
