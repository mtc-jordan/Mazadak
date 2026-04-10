"use client";

import Link from "next/link";
import { Shield, Scale, Users } from "lucide-react";

export default function AdminDashboard() {
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold text-navy font-sora">
        Admin Dashboard
      </h1>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Link href="/admin/moderation" className="card hover:border-navy/30 transition-colors group">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-gold/10 flex items-center justify-center">
              <Shield size={20} className="text-gold" />
            </div>
            <h2 className="font-sora font-bold text-navy">Moderation</h2>
          </div>
          <p className="text-sm text-mist">
            Review listings awaiting approval, sorted by AI risk score
          </p>
        </Link>

        <Link href="/admin/disputes" className="card hover:border-navy/30 transition-colors group">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-ember/10 flex items-center justify-center">
              <Scale size={20} className="text-ember" />
            </div>
            <h2 className="font-sora font-bold text-navy">Disputes</h2>
          </div>
          <p className="text-sm text-mist">
            Resolve buyer-seller disputes with evidence review
          </p>
        </Link>

        <Link href="/admin/users" className="card hover:border-navy/30 transition-colors group">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-emerald/10 flex items-center justify-center">
              <Users size={20} className="text-emerald" />
            </div>
            <h2 className="font-sora font-bold text-navy">Users</h2>
          </div>
          <p className="text-sm text-mist">
            Search, review, and manage user accounts
          </p>
        </Link>
      </div>
    </div>
  );
}
