import 'package:flutter/services.dart';

/// Semantic haptic feedback for MZADAK auction interactions.
abstract final class AppHaptics {
  /// Light tap when user taps the bid button.
  static Future<void> bidTap() => HapticFeedback.lightImpact();

  /// Medium + success pattern when bid is confirmed by server.
  static Future<void> bidConfirmed() => HapticFeedback.mediumImpact();

  /// Heavy vibration when user is outbid — attention-grabbing.
  static Future<void> outbid() => HapticFeedback.heavyImpact();

  /// Selection click for payment success.
  static Future<void> paymentSuccess() => HapticFeedback.mediumImpact();

  /// Notification received.
  static Future<void> notification() => HapticFeedback.selectionClick();

  /// Error / failure feedback.
  static Future<void> error() => HapticFeedback.vibrate();
}
