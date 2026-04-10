"use client";

import { useState, useEffect } from "react";
import { elapsed, isOverdue } from "@/lib/utils";

/**
 * Live countdown/elapsed timer that ticks every second.
 * Returns { display, overdue }.
 */
export function useTimer(iso: string, slaHours?: number) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  return {
    display: elapsed(iso),
    overdue: slaHours ? isOverdue(iso, slaHours) : false,
  };
}
