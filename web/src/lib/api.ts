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

// 401 response interceptor — attempt token refresh (with shared promise to
// prevent concurrent refresh races)
let refreshPromise: Promise<string> | null = null;

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      typeof window !== "undefined"
    ) {
      originalRequest._retry = true;

      const refreshToken = localStorage.getItem("admin_refresh_token");
      if (refreshToken) {
        try {
          // Reuse in-flight refresh if one is already running
          if (!refreshPromise) {
            refreshPromise = axios
              .post(`${BASE}/api/v1/auth/refresh`, {
                refresh_token: refreshToken,
              })
              .then((res) => {
                const { access_token, refresh_token: newRefresh } = res.data;
                localStorage.setItem("admin_token", access_token);
                if (newRefresh) {
                  localStorage.setItem("admin_refresh_token", newRefresh);
                }
                return access_token as string;
              })
              .finally(() => {
                refreshPromise = null;
              });
          }

          const accessToken = await refreshPromise;
          originalRequest.headers.Authorization = `Bearer ${accessToken}`;
          return api(originalRequest);
        } catch {
          // Refresh failed — clear and redirect
          localStorage.removeItem("admin_token");
          localStorage.removeItem("admin_refresh_token");
          window.location.href = "/login";
          return Promise.reject(error);
        }
      }

      // No refresh token — clear and redirect
      localStorage.removeItem("admin_token");
      localStorage.removeItem("admin_refresh_token");
      window.location.href = "/login";
    }

    return Promise.reject(error);
  }
);

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

// ── KYC Review ──────────────────────────────────────────────

export const kyc = {
  queue: () => api.get("/admin/kyc/queue"),
  documentUrl: (docId: string) =>
    api.get(`/admin/kyc/documents/${docId}/url`),
  approve: (userId: string) => api.post(`/admin/kyc/${userId}/approve`),
  reject: (userId: string, reason: string) =>
    api.post(`/admin/kyc/${userId}/reject`, { reason }),
};

// ── B2B Tender Rooms ────────────────────────────────────────

import type {
  B2BCreateRoomRequest,
  B2BInviteRequest,
} from "./types";

export const tenders = {
  list: (params?: { status?: string; page?: number; per_page?: number }) =>
    api.get("/admin/tenders/", { params }),

  get: (id: string) => api.get(`/admin/tenders/${id}`),

  create: (data: B2BCreateRoomRequest) =>
    api.post("/admin/tenders/", data),

  update: (
    id: string,
    data: Partial<{
      status: string;
      submission_deadline: string;
      description: string;
      client_logo_url: string;
      estimated_value: number;
    }>
  ) => api.patch(`/admin/tenders/${id}`, data),

  invite: (id: string, data: B2BInviteRequest) =>
    api.post(`/admin/tenders/${id}/invite`, data),

  revokeInvitation: (id: string, invitationId: string) =>
    api.delete(`/admin/tenders/${id}/invitations/${invitationId}`),

  announce: (id: string, winnerBidId: string) =>
    api.post(`/admin/tenders/${id}/announce`, { winner_bid_id: winnerBidId }),

  analytics: (id: string) => api.get(`/admin/tenders/${id}/analytics`),

  exportCompliancePdf: (id: string) =>
    api.get(`/admin/tenders/${id}/export/compliance-pdf`, {
      responseType: "blob",
    }),

  exportAwardLetter: (id: string, bidId: string) =>
    api.get(`/admin/tenders/${id}/export/award-letter/${bidId}`, {
      responseType: "blob",
    }),

  importCsv: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return api.post("/admin/tenders/import-csv", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
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
