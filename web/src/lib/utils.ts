import { clsx, type ClassValue } from "clsx";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

/** Format ISO date to relative time: "2m ago", "3h ago", "2d ago" */
export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/** Elapsed time since ISO date in HH:MM:SS */
export function elapsed(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "00:00:00";
  const h = Math.floor(diff / 3_600_000);
  const m = Math.floor((diff % 3_600_000) / 60_000);
  const s = Math.floor((diff % 60_000) / 1_000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Is the ISO date older than the given hours? */
export function isOverdue(iso: string, hours: number): boolean {
  return Date.now() - new Date(iso).getTime() > hours * 3_600_000;
}

/** Format currency: "620 JOD" */
export function formatCurrency(amount: number, currency: string): string {
  return `${amount.toLocaleString("en-US", {
    minimumFractionDigits: currency === "JOD" ? 3 : 2,
    maximumFractionDigits: currency === "JOD" ? 3 : 2,
  })} ${currency}`;
}

/** Mask a phone number: +962 7XX XXX XX3 */
export function maskPhone(phone: string): string {
  if (phone.length < 6) return phone;
  return phone.slice(0, 5) + "** ***" + phone.slice(-2);
}
