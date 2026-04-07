import 'package:flutter/material.dart';

/// MZADAK color tokens — brand palette.
abstract final class AppColors {
  // ── Brand primaries ─────────────────────────────────────────────
  static const navy   = Color(0xFF1C3557);
  static const gold   = Color(0xFF9A6420);
  static const cream  = Color(0xFFFBF5E8);
  static const sand   = Color(0xFFF0EAD8);

  // ── Neutrals ────────────────────────────────────────────────────
  static const ink    = Color(0xFF1A1814);
  static const mist   = Color(0xFF8A8275);

  // ── Accents ─────────────────────────────────────────────────────
  static const ember   = Color(0xFFC4420A);
  static const emerald = Color(0xFF0D5C3A);

  // ── Semantic (light) ────────────────────────────────────────────
  static const surface       = cream;
  static const surfaceAlt    = sand;
  static const onSurface     = ink;
  static const onSurfaceDim  = mist;
  static const primary       = navy;
  static const onPrimary     = Color(0xFFFFFFFF);
  static const secondary     = gold;
  static const onSecondary   = Color(0xFFFFFFFF);
  static const error         = ember;
  static const onError       = Color(0xFFFFFFFF);
  static const success       = emerald;
  static const onSuccess     = Color(0xFFFFFFFF);

  // ── Semantic (dark) ─────────────────────────────────────────────
  static const darkSurface      = Color(0xFF121210);
  static const darkSurfaceAlt   = Color(0xFF1E1D1A);
  static const darkOnSurface    = Color(0xFFE8E2D6);
  static const darkOnSurfaceDim = Color(0xFF6E695F);
  static const darkPrimary      = Color(0xFF4A7AB5);
  static const darkSecondary    = Color(0xFFC8923E);
  static const darkError        = Color(0xFFE87351);
  static const darkSuccess      = Color(0xFF30A06A);
}
