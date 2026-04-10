import axios from "axios";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${BASE}/api/v1`,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

// Attach JWT from cookie/localStorage on every request
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("admin_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
  }
  return config;
});

// ── Moderation ──────────────────────────────────────────────

export const moderation = {
  list: (params?: Record<string, string | number>) =>
    api.get("/admin/moderation", { params }),
  get: (id: string) => api.get(`/admin/moderation/${id}`),
  approve: (id: string) =>
    api.post(`/admin/moderation/${id}/approve`),
  reject: (id: string, reason: string) =>
    api.post(`/admin/moderation/${id}/reject`, { reason }),
  requireEdit: (id: string, reason: string) =>
    api.post(`/admin/moderation/${id}/require-edit`, { reason }),
  escalate: (id: string, reason: string) =>
    api.post(`/admin/moderation/${id}/escalate`, { reason }),
  sellerHistory: (sellerId: string) =>
    api.get(`/admin/users/${sellerId}/seller-history`),
};

// ── Disputes ────────────────────────────────────────────────

export const disputes = {
  list: (params?: Record<string, string | number>) =>
    api.get("/admin/disputes", { params }),
  get: (id: string) => api.get(`/admin/disputes/${id}`),
  resolve: (
    id: string,
    data: {
      outcome: string;
      reason_code: string;
      reason_text: string;
      refund_amount?: number;
    }
  ) => api.post(`/admin/disputes/${id}/resolve`, data),
};

// ── Users ───────────────────────────────────────────────────

export const users = {
  search: (query: string) =>
    api.get("/admin/users", { params: { q: query } }),
  get: (id: string) => api.get(`/admin/users/${id}`),
  warn: (id: string, reason: string) =>
    api.post(`/admin/users/${id}/warn`, { reason }),
  suspend: (id: string, reason: string) =>
    api.post(`/admin/users/${id}/suspend`, { reason }),
  ban: (id: string, reason: string) =>
    api.post(`/admin/users/${id}/ban`, { reason }),
  restore: (id: string, reason: string) =>
    api.post(`/admin/users/${id}/restore`, { reason }),
};

// ── Audit Log ───────────────────────────────────────────────

export const auditLog = {
  create: (entry: {
    action: string;
    target_type: string;
    target_id: string;
    reason: string;
    metadata?: Record<string, unknown>;
  }) => api.post("/admin/audit-log", entry),
};
