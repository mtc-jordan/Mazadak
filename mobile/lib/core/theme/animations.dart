import 'package:flutter/animation.dart';

/// Canonical animation durations and curves for MZADAK.
abstract final class AppAnimations {
  // ── Durations ───────────────────────────────────────────────────

  /// Micro-interactions: toggles, checkboxes, icon morphs.
  static const microMs  = 120;
  static const micro    = Duration(milliseconds: microMs);

  /// State changes: button press feedback, card selection.
  static const stateMs  = 240;
  static const state    = Duration(milliseconds: stateMs);

  /// Enter/appear transitions: sheets, modals, new elements.
  static const enterMs  = 400;
  static const enter    = Duration(milliseconds: enterMs);

  /// Long transitions: page routes, complex orchestrations.
  static const longMs   = 600;
  static const long     = Duration(milliseconds: longMs);

  // ── Curves ──────────────────────────────────────────────────────

  /// Spring-like overshoot for bid confirmations, success states.
  static const springCurve = Curves.elasticOut;

  /// Standard enter: elements appearing on screen.
  static const enterCurve = Curves.easeOutCubic;

  /// Exit: elements leaving the screen.
  static const exitCurve = Curves.easeIn;

  /// Shared-axis: page transitions.
  static const sharedAxis = Curves.easeInOutCubic;
}
