"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { api } from "./api";

// ── Types ────────────────────────────────────────────────────

interface User {
  id: string;
  phone: string;
  role: string;
  name: string;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (phone: string) => Promise<void>;
  verifyOtp: (phone: string, otp: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => Promise<void>;
  isAuthenticated: boolean;
}

// ── Context ──────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ── Provider ─────────────────────────────────────────────────

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  // Check existing session on mount
  useEffect(() => {
    const token = localStorage.getItem("admin_token");
    if (!token) {
      setLoading(false);
      return;
    }

    api
      .get("/auth/me")
      .then((res) => {
        const data = res.data;
        if (data.role === "admin" || data.role === "superadmin") {
          setUser({
            id: data.id,
            phone: data.phone,
            role: data.role,
            name: data.full_name_ar || data.phone,
          });
        } else {
          // Not an admin — clear tokens
          localStorage.removeItem("admin_token");
          localStorage.removeItem("admin_refresh_token");
        }
      })
      .catch(() => {
        localStorage.removeItem("admin_token");
        localStorage.removeItem("admin_refresh_token");
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (phone: string) => {
    await api.post("/auth/register", { phone });
  }, []);

  const verifyOtp = useCallback(
    async (
      phone: string,
      otp: string
    ): Promise<{ success: boolean; error?: string }> => {
      const res = await api.post("/auth/verify-otp", { phone, otp });
      const data = res.data;

      const role = data.user?.role ?? data.role;
      if (role !== "admin" && role !== "superadmin") {
        return { success: false, error: "Access denied. Admin accounts only." };
      }

      // Store tokens
      localStorage.setItem("admin_token", data.access_token);
      if (data.refresh_token) {
        localStorage.setItem("admin_refresh_token", data.refresh_token);
      }

      const u = data.user ?? data;
      setUser({
        id: u.id,
        phone: u.phone,
        role: u.role,
        name: u.full_name_ar || u.phone,
      });

      return { success: true };
    },
    []
  );

  const logout = useCallback(async () => {
    try {
      const refreshToken = localStorage.getItem("admin_refresh_token");
      await api.post("/auth/logout", {
        refresh_token: refreshToken || "",
        revoke_all: false,
      });
    } catch {
      // Ignore — we clear locally regardless
    }
    localStorage.removeItem("admin_token");
    localStorage.removeItem("admin_refresh_token");
    setUser(null);
    router.push("/login");
  }, [router]);

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        verifyOtp,
        logout,
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ─────────────────────────────────────────────────────

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

// ── Guard ────────────────────────────────────────────────────

export function AuthGuard({ children }: { children: ReactNode }) {
  const { user, loading, isAuthenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.push("/login");
    }
  }, [loading, isAuthenticated, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-cream">
        <div className="animate-pulse text-navy font-sora font-bold text-lg">
          Loading...
        </div>
      </div>
    );
  }

  if (!isAuthenticated || !user) {
    return null;
  }

  // Extra guard: must be admin/superadmin
  if (user.role !== "admin" && user.role !== "superadmin") {
    router.push("/login");
    return null;
  }

  return <>{children}</>;
}
