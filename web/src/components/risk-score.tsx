import { cn } from "@/lib/utils";

/**
 * Visual risk score indicator: 0-100 with color coding.
 * 0-30 green, 31-60 amber, 61-100 red.
 */
export function RiskScore({ score }: { score: number }) {
  const color =
    score <= 30
      ? "text-emerald bg-emerald/10"
      : score <= 60
        ? "text-amber-600 bg-amber-100"
        : "text-ember bg-ember/10";

  return (
    <span
      className={cn(
        "inline-flex items-center justify-center w-10 h-6 rounded text-xs font-bold font-mono",
        color
      )}
    >
      {score}
    </span>
  );
}
