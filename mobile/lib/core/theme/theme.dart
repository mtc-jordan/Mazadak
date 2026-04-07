import 'package:flutter/material.dart';

import 'colors.dart';
import 'spacing.dart';
import 'typography.dart';

/// MZADAK Material 3 theme configuration.
///
/// Usage:
///   theme: MzadakTheme.light(),
///   darkTheme: MzadakTheme.dark(),
abstract final class MzadakTheme {
  // ═══════════════════════════════════════════════════════════════
  //  Light theme
  // ═══════════════════════════════════════════════════════════════

  static ThemeData light() {
    final textTheme = AppTypography.textTheme(brightness: Brightness.light);

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      colorScheme: const ColorScheme.light(
        primary: AppColors.primary,
        onPrimary: AppColors.onPrimary,
        secondary: AppColors.secondary,
        onSecondary: AppColors.onSecondary,
        surface: AppColors.surface,
        onSurface: AppColors.onSurface,
        surfaceContainerHighest: AppColors.surfaceAlt,
        error: AppColors.error,
        onError: AppColors.onError,
      ),
      scaffoldBackgroundColor: AppColors.surface,
      textTheme: textTheme,

      // ── AppBar ─────────────────────────────────────────────────
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.navy,
        foregroundColor: AppColors.onPrimary,
        elevation: 0,
        centerTitle: true,
        titleTextStyle: textTheme.headlineMedium?.copyWith(
          color: AppColors.onPrimary,
          fontSize: 18,
        ),
      ),

      // ── Cards ──────────────────────────────────────────────────
      cardTheme: CardThemeData(
        color: Colors.white,
        elevation: 1,
        shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusLg),
        margin: AppSpacing.allSm,
      ),

      // ── Elevated Button ────────────────────────────────────────
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.gold,
          foregroundColor: AppColors.onSecondary,
          elevation: 0,
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusMd),
          textStyle: textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
        ),
      ),

      // ── Outlined Button ────────────────────────────────────────
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.navy,
          side: const BorderSide(color: AppColors.navy, width: 1.5),
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusMd),
        ),
      ),

      // ── Text Button ────────────────────────────────────────────
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: AppColors.navy,
          textStyle: textTheme.titleMedium,
        ),
      ),

      // ── Input ──────────────────────────────────────────────────
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        contentPadding: AppSpacing.allMd,
        border: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.sand, width: 1.5),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.sand, width: 1.5),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.navy, width: 2),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.ember, width: 1.5),
        ),
        hintStyle: textTheme.bodyMedium?.copyWith(color: AppColors.mist),
      ),

      // ── Bottom Nav ─────────────────────────────────────────────
      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: Colors.white,
        selectedItemColor: AppColors.navy,
        unselectedItemColor: AppColors.mist,
        type: BottomNavigationBarType.fixed,
        elevation: 8,
      ),

      // ── Chip ───────────────────────────────────────────────────
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.sand,
        selectedColor: AppColors.navy,
        labelStyle: textTheme.labelSmall,
        shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusFull),
        side: BorderSide.none,
        padding: AppSpacing.horizontalSm,
      ),

      // ── Divider ────────────────────────────────────────────────
      dividerTheme: const DividerThemeData(
        color: AppColors.sand,
        thickness: 1,
        space: 0,
      ),

      // ── SnackBar ───────────────────────────────────────────────
      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.ink,
        contentTextStyle: textTheme.bodyMedium?.copyWith(color: Colors.white),
        shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusMd),
        behavior: SnackBarBehavior.floating,
      ),

      // ── Page transitions ───────────────────────────────────────
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: FadeUpwardsPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }

  // ═══════════════════════════════════════════════════════════════
  //  Dark theme
  // ═══════════════════════════════════════════════════════════════

  static ThemeData dark() {
    final textTheme = AppTypography.textTheme(brightness: Brightness.dark);

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.darkPrimary,
        onPrimary: Colors.white,
        secondary: AppColors.darkSecondary,
        onSecondary: Colors.white,
        surface: AppColors.darkSurface,
        onSurface: AppColors.darkOnSurface,
        surfaceContainerHighest: AppColors.darkSurfaceAlt,
        error: AppColors.darkError,
        onError: Colors.white,
      ),
      scaffoldBackgroundColor: AppColors.darkSurface,
      textTheme: textTheme,

      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.darkSurfaceAlt,
        foregroundColor: AppColors.darkOnSurface,
        elevation: 0,
        centerTitle: true,
        titleTextStyle: textTheme.headlineMedium?.copyWith(
          color: AppColors.darkOnSurface,
          fontSize: 18,
        ),
      ),

      cardTheme: CardThemeData(
        color: AppColors.darkSurfaceAlt,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusLg),
        margin: AppSpacing.allSm,
      ),

      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.darkSecondary,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusMd),
          textStyle: textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w600),
        ),
      ),

      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.darkPrimary,
          side: const BorderSide(color: AppColors.darkPrimary, width: 1.5),
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.lg,
            vertical: AppSpacing.sm,
          ),
          shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusMd),
        ),
      ),

      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AppColors.darkSurfaceAlt,
        contentPadding: AppSpacing.allMd,
        border: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.darkOnSurfaceDim, width: 1),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.darkOnSurfaceDim, width: 1),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.darkPrimary, width: 2),
        ),
        hintStyle: textTheme.bodyMedium?.copyWith(color: AppColors.darkOnSurfaceDim),
      ),

      bottomNavigationBarTheme: const BottomNavigationBarThemeData(
        backgroundColor: AppColors.darkSurfaceAlt,
        selectedItemColor: AppColors.darkPrimary,
        unselectedItemColor: AppColors.darkOnSurfaceDim,
        type: BottomNavigationBarType.fixed,
        elevation: 0,
      ),

      chipTheme: ChipThemeData(
        backgroundColor: AppColors.darkSurfaceAlt,
        selectedColor: AppColors.darkPrimary,
        labelStyle: textTheme.labelSmall,
        shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusFull),
        side: BorderSide.none,
      ),

      dividerTheme: const DividerThemeData(
        color: AppColors.darkOnSurfaceDim,
        thickness: 0.5,
        space: 0,
      ),

      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.darkOnSurface,
        contentTextStyle: textTheme.bodyMedium?.copyWith(color: AppColors.darkSurface),
        shape: RoundedRectangleBorder(borderRadius: AppSpacing.radiusMd),
        behavior: SnackBarBehavior.floating,
      ),

      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.android: FadeUpwardsPageTransitionsBuilder(),
          TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        },
      ),
    );
  }
}
