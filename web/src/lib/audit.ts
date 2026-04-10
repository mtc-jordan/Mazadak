import { auditLog } from "./api";
import type { AdminAction } from "./types";

/**
 * Wraps an admin action: logs to audit trail BEFORE executing the action.
 *
 * Every admin mutation MUST go through this function to satisfy the
 * requirement that POST /api/v1/admin/audit-log is called before executing.
 */
export async function withAuditLog<T>(
  params: {
    action: AdminAction;
    targetType: "user" | "listing" | "dispute";
    targetId: string;
    reason: string;
    metadata?: Record<string, unknown>;
  },
  execute: () => Promise<T>
): Promise<T> {
  // Step 1: Log the audit entry BEFORE the action
  await auditLog.create({
    action: params.action,
    target_type: params.targetType,
    target_id: params.targetId,
    reason: params.reason,
    metadata: params.metadata,
  });

  // Step 2: Execute the actual action
  return execute();
}
