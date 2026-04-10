import 'package:flutter/material.dart';

/// 8px grid spacing system.
abstract final class AppSpacing {
  static const double xxs = 4;
  static const double xs  = 8;
  static const double sm  = 12;
  static const double md  = 16;
  static const double lg  = 24;
  static const double xl  = 32;
  static const double xxl = 40;
  static const double xxxl = 56;

  /// Gap between home-feed sections.
  static const double sectionGap = 28;

  // ── Convenience EdgeInsets (RTL-safe: start/end, not left/right) ─

  static const horizontalXs  = EdgeInsetsDirectional.symmetric(horizontal: xs);
  static const horizontalSm  = EdgeInsetsDirectional.symmetric(horizontal: sm);
  static const horizontalMd  = EdgeInsetsDirectional.symmetric(horizontal: md);
  static const horizontalLg  = EdgeInsetsDirectional.symmetric(horizontal: lg);

  static const verticalXs = EdgeInsetsDirectional.symmetric(vertical: xs);
  static const verticalSm = EdgeInsetsDirectional.symmetric(vertical: sm);
  static const verticalMd = EdgeInsetsDirectional.symmetric(vertical: md);
  static const verticalLg = EdgeInsetsDirectional.symmetric(vertical: lg);

  static const allXs  = EdgeInsetsDirectional.all(xs);
  static const allSm  = EdgeInsetsDirectional.all(sm);
  static const allMd  = EdgeInsetsDirectional.all(md);
  static const allLg  = EdgeInsetsDirectional.all(lg);
  static const allXl  = EdgeInsetsDirectional.all(xl);

  // ── Border radii ────────────────────────────────────────────────

  static final radiusSm  = BorderRadius.circular(xs);
  static final radiusMd  = BorderRadius.circular(sm);
  static final radiusLg  = BorderRadius.circular(md);
  static final radiusXl  = BorderRadius.circular(lg);
  static final radiusFull = BorderRadius.circular(999);
}
