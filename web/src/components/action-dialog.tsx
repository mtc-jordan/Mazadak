"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";

interface ActionDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  requireReason?: boolean;
  minReasonLength?: number;
  confirmLabel: string;
  confirmVariant?: "danger" | "primary" | "gold";
  onConfirm: (reason: string) => Promise<void>;
}

const variantClass = {
  danger: "btn-danger",
  primary: "btn-primary",
  gold: "btn-gold",
};

export function ActionDialog({
  open,
  onClose,
  title,
  description,
  requireReason = true,
  minReasonLength = 10,
  confirmLabel,
  confirmVariant = "primary",
  onConfirm,
}: ActionDialogProps) {
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);

  if (!open) return null;

  const canSubmit =
    !loading && (!requireReason || reason.trim().length >= minReasonLength);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setLoading(true);
    try {
      await onConfirm(reason.trim());
      setReason("");
      onClose();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-ink/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-mist hover:text-ink"
        >
          <X size={18} />
        </button>

        <h3 className="text-lg font-bold text-navy font-sora">{title}</h3>
        {description && (
          <p className="mt-1 text-sm text-mist">{description}</p>
        )}

        {requireReason && (
          <div className="mt-4">
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Reason (required)..."
              rows={3}
              className="w-full border border-sand rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-navy resize-none"
            />
            <p className="text-xs text-mist mt-1">
              {reason.length}/{minReasonLength} min characters
            </p>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="btn-outline">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className={cn(
              variantClass[confirmVariant],
              !canSubmit && "opacity-40 cursor-not-allowed"
            )}
          >
            {loading ? (
              <span className="inline-flex items-center gap-2">
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Working...
              </span>
            ) : (
              confirmLabel
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
