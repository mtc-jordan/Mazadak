import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// MZADAK type scale.
///
/// Primary: Sora (Latin/numerals). Arabic: Noto Kufi Arabic.
/// Both loaded via Google Fonts with local fallback.
abstract final class AppTypography {
  // ── Base text themes ────────────────────────────────────────────

  static TextTheme get _sora => GoogleFonts.soraTextTheme();

  static TextTheme get _notoKufi => GoogleFonts.notoKufiArabicTextTheme();

  /// Merged text theme: Sora base with Noto Kufi Arabic fallback.
  static TextTheme textTheme({Brightness brightness = Brightness.light}) {
    final base = _sora;
    return base.copyWith(
      // display — 32sp / 700
      displayLarge: _display(base, brightness),
      // heading — 22sp / 600
      headlineMedium: _heading(base, brightness),
      // subheading — 16sp / 500
      titleMedium: _subheading(base, brightness),
      // body — 14sp / 400
      bodyMedium: _body(base, brightness),
      // caption — 11sp / 600 / UPPERCASE (applied via widget)
      labelSmall: _caption(base, brightness),
    );
  }

  /// Arabic-specific text theme for RTL layouts.
  static TextTheme arabicTextTheme({Brightness brightness = Brightness.light}) {
    final base = _notoKufi;
    return base.copyWith(
      displayLarge: _display(base, brightness),
      headlineMedium: _heading(base, brightness),
      titleMedium: _subheading(base, brightness),
      bodyMedium: _body(base, brightness),
      labelSmall: _caption(base, brightness),
    );
  }

  // ── Type scale steps ────────────────────────────────────────────

  static TextStyle _display(TextTheme base, Brightness b) =>
      (base.displayLarge ?? const TextStyle()).copyWith(
        fontSize: 32,
        fontWeight: FontWeight.w700,
        height: 1.25,
      );

  static TextStyle _heading(TextTheme base, Brightness b) =>
      (base.headlineMedium ?? const TextStyle()).copyWith(
        fontSize: 22,
        fontWeight: FontWeight.w600,
        height: 1.3,
      );

  static TextStyle _subheading(TextTheme base, Brightness b) =>
      (base.titleMedium ?? const TextStyle()).copyWith(
        fontSize: 16,
        fontWeight: FontWeight.w500,
        height: 1.4,
      );

  static TextStyle _body(TextTheme base, Brightness b) =>
      (base.bodyMedium ?? const TextStyle()).copyWith(
        fontSize: 14,
        fontWeight: FontWeight.w400,
        height: 1.5,
      );

  static TextStyle _caption(TextTheme base, Brightness b) =>
      (base.labelSmall ?? const TextStyle()).copyWith(
        fontSize: 11,
        fontWeight: FontWeight.w600,
        letterSpacing: 0.8,
        height: 1.4,
      );
}
