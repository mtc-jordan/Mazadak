"use client";

import { useTimer } from "@/hooks/use-timer";
import { cn } from "@/lib/utils";
import { Clock } from "lucide-react";

/**
 * Live SLA timer that turns red when overdue.
 */
export function SlaTimer({
  since,
  slaHours = 2,
}: {
  since: string;
  slaHours?: number;
}) {
  const { display, overdue } = useTimer(since, slaHours);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 text-xs font-mono font-semibold",
        overdue ? "text-ember" : "text-mist"
      )}
    >
      <Clock size={12} className={overdue ? "animate-pulse" : ""} />
      {display}
    </span>
  );
}
