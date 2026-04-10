import { cn } from "@/lib/utils";

type Variant =
  | "navy"
  | "gold"
  | "ember"
  | "emerald"
  | "mist"
  | "amber";

const variants: Record<Variant, string> = {
  navy: "bg-navy/10 text-navy",
  gold: "bg-gold/10 text-gold",
  ember: "bg-ember/10 text-ember",
  emerald: "bg-emerald/10 text-emerald",
  mist: "bg-sand text-mist",
  amber: "bg-amber-100 text-amber-700",
};

export function Badge({
  children,
  variant = "mist",
  className,
  pulse,
}: {
  children: React.ReactNode;
  variant?: Variant;
  className?: string;
  pulse?: boolean;
}) {
  return (
    <span
      className={cn(
        "badge",
        variants[variant],
        pulse && "animate-pulse-slow",
        className
      )}
    >
      {children}
    </span>
  );
}
