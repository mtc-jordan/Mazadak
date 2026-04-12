"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const { login, verifyOtp, isAuthenticated } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState<"phone" | "otp">("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [resendTimer, setResendTimer] = useState(0);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated) {
      router.push("/admin");
    }
  }, [isAuthenticated, router]);

  // Resend countdown
  useEffect(() => {
    if (resendTimer > 0) {
      timerRef.current = setInterval(() => {
        setResendTimer((t) => {
          if (t <= 1) {
            if (timerRef.current) clearInterval(timerRef.current);
            return 0;
          }
          return t - 1;
        });
      }, 1000);
      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
      };
    }
  }, [resendTimer]);

  const handleSendOtp = async () => {
    setError("");
    const cleaned = phone.replace(/\s/g, "");
    if (!/^\d{9}$/.test(cleaned)) {
      setError("Enter a valid 9-digit Jordanian number");
      return;
    }

    setSending(true);
    try {
      await login(`+962${cleaned}`);
      setStep("otp");
      setResendTimer(60);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Failed to send OTP. Try again.";
      setError(msg);
    } finally {
      setSending(false);
    }
  };

  const handleVerify = async () => {
    setError("");
    if (otp.length !== 6) {
      setError("Enter the 6-digit code");
      return;
    }

    setVerifying(true);
    try {
      const result = await verifyOtp(`+962${phone.replace(/\s/g, "")}`, otp);
      if (result.success) {
        router.push("/admin");
      } else {
        setError(result.error || "Verification failed");
      }
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Invalid OTP. Try again.";
      setError(msg);
    } finally {
      setVerifying(false);
    }
  };

  const handleResend = async () => {
    setError("");
    setSending(true);
    try {
      await login(`+962${phone.replace(/\s/g, "")}`);
      setResendTimer(60);
    } catch {
      setError("Failed to resend OTP");
    } finally {
      setSending(false);
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: "#0A1628" }}
    >
      {/* Subtle radial glow behind the card */}
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background:
            "radial-gradient(ellipse at 50% 40%, rgba(197,160,40,0.08) 0%, transparent 70%)",
        }}
      />

      <div
        className="relative w-full max-w-md rounded-2xl shadow-2xl p-8 border"
        style={{
          backgroundColor: "#0F1D32",
          borderColor: "rgba(197,160,40,0.15)",
        }}
      >
        {/* Header */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-extrabold font-sora text-white">
            <span style={{ color: "#C5A028" }}>م</span> MZADAK
          </h1>
          <p className="mt-1 text-sm text-white/40 tracking-widest uppercase">
            Admin Panel
          </p>
        </div>

        {step === "phone" ? (
          /* ── Step 1: Phone ────────────────────────────────── */
          <div className="space-y-5">
            <div>
              <label className="block text-sm font-medium mb-1.5 text-white/70">
                Phone Number
              </label>
              <div className="flex rounded-lg overflow-hidden border border-white/10 focus-within:ring-2 focus-within:ring-[#C5A028]/50">
                <span
                  className="flex items-center px-3 text-sm font-medium text-white/90"
                  style={{ backgroundColor: "#C5A028" }}
                >
                  +962
                </span>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) =>
                    setPhone(e.target.value.replace(/\D/g, "").slice(0, 9))
                  }
                  placeholder="7XXXXXXXX"
                  className="flex-1 px-3 py-2.5 text-sm outline-none bg-[#162440] text-white placeholder-white/30"
                  maxLength={9}
                  onKeyDown={(e) => e.key === "Enter" && handleSendOtp()}
                />
              </div>
            </div>

            {error && (
              <p className="text-sm text-red-400 bg-red-900/30 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              onClick={handleSendOtp}
              disabled={sending}
              className="w-full py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 hover:brightness-110"
              style={{ backgroundColor: "#C5A028", color: "#0A1628" }}
            >
              {sending ? "Sending..." : "Send OTP"}
            </button>
          </div>
        ) : (
          /* ── Step 2: OTP ─────────────────────────────────── */
          <div className="space-y-5">
            <p className="text-sm text-center text-white/70">
              Enter the 6-digit code sent to{" "}
              <span className="font-semibold text-white">+962{phone}</span>
            </p>

            <div>
              <input
                type="text"
                inputMode="numeric"
                value={otp}
                onChange={(e) =>
                  setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))
                }
                placeholder="000000"
                className="w-full text-center tracking-[0.4em] text-xl font-mono py-3 rounded-lg border border-white/10 focus:ring-2 focus:ring-[#C5A028]/50 outline-none bg-[#162440] text-white placeholder-white/20"
                maxLength={6}
                autoFocus
                onKeyDown={(e) => e.key === "Enter" && handleVerify()}
              />
            </div>

            {error && (
              <p className="text-sm text-red-400 bg-red-900/30 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              onClick={handleVerify}
              disabled={verifying}
              className="w-full py-2.5 rounded-lg text-sm font-semibold transition-all disabled:opacity-50 hover:brightness-110"
              style={{ backgroundColor: "#C5A028", color: "#0A1628" }}
            >
              {verifying ? "Verifying..." : "Verify & Login"}
            </button>

            <div className="flex items-center justify-between text-sm">
              <button
                onClick={() => {
                  setStep("phone");
                  setOtp("");
                  setError("");
                }}
                className="underline text-white/50 hover:text-white/80 transition-colors"
              >
                Change number
              </button>

              {resendTimer > 0 ? (
                <span className="text-white/30">
                  Resend in {resendTimer}s
                </span>
              ) : (
                <button
                  onClick={handleResend}
                  disabled={sending}
                  className="underline font-medium transition-colors hover:brightness-110"
                  style={{ color: "#C5A028" }}
                >
                  Resend OTP
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
