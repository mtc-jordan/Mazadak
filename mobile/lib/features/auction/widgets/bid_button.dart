import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/animations.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/haptics.dart';
import '../../../core/theme/spacing.dart';

/// The 5 visual states of the bid button.
enum BidButtonState { idle, loading, leading, outbid, disabled }

/// Bid button with 5 animated states and haptic feedback.
///
/// SDD §7.2:
/// IDLE:     gold background, "Place bid"
/// LOADING:  circular progress, pulsing opacity
/// LEADING:  emerald background, pulse scale 1.0→1.04 loop, "You're leading!"
/// OUTBID:   ember background, shake ±4px 3 cycles, heavy haptic
/// DISABLED: muted gray
///
/// Spring transitions between all states using AnimationController + TweenSequence.
class BidButton extends StatefulWidget {
  const BidButton({
    super.key,
    required this.state,
    required this.onPressed,
    this.label,
  });

  final BidButtonState state;
  final VoidCallback? onPressed;
  final String? label;

  @override
  State<BidButton> createState() => _BidButtonState();
}

class _BidButtonState extends State<BidButton> with TickerProviderStateMixin {
  // ── Pulse animation (LEADING state) ─────────────────────────────
  late AnimationController _pulseController;
  late Animation<double> _pulseScale;

  // ── Shake animation (OUTBID state) ──────────────────────────────
  late AnimationController _shakeController;
  late Animation<double> _shakeOffset;

  // ── Opacity pulse (LOADING state) ───────────────────────────────
  late AnimationController _opacityController;
  late Animation<double> _opacityPulse;

  // ── Color/scale spring transition ───────────────────────────────
  late AnimationController _springController;

  BidButtonState _previousState = BidButtonState.idle;

  @override
  void initState() {
    super.initState();

    // Leading pulse: scale 1.0→1.04 repeating
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    );
    _pulseScale = TweenSequence<double>([
      TweenSequenceItem(
        tween: Tween(begin: 1.0, end: 1.04)
            .chain(CurveTween(curve: Curves.easeOut)),
        weight: 50,
      ),
      TweenSequenceItem(
        tween: Tween(begin: 1.04, end: 1.0)
            .chain(CurveTween(curve: Curves.easeIn)),
        weight: 50,
      ),
    ]).animate(_pulseController);

    // Outbid shake: ±4px, 3 cycles
    _shakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _shakeOffset = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: 4), weight: 1),
      TweenSequenceItem(tween: Tween(begin: 4, end: -4), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -4, end: 4), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 4, end: -4), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -4, end: 4), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 4, end: -4), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -4, end: 0), weight: 1),
    ]).animate(CurvedAnimation(
      parent: _shakeController,
      curve: Curves.easeInOut,
    ));

    // Loading opacity pulse
    _opacityController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _opacityPulse = Tween<double>(begin: 1.0, end: 0.5).animate(
      CurvedAnimation(parent: _opacityController, curve: Curves.easeInOut),
    );

    // Spring controller for cross-state transitions
    _springController = AnimationController(
      vsync: this,
      duration: AppAnimations.state,
    );

    _applyState(widget.state);
  }

  @override
  void didUpdateWidget(BidButton old) {
    super.didUpdateWidget(old);
    if (old.state != widget.state) {
      _previousState = old.state;
      _applyState(widget.state);
    }
  }

  void _applyState(BidButtonState newState) {
    // Stop all animations first
    _pulseController.stop();
    _shakeController.stop();
    _opacityController.stop();
    _springController.forward(from: 0);

    switch (newState) {
      case BidButtonState.idle:
        AppHaptics.bidTap();
      case BidButtonState.loading:
        _opacityController.repeat(reverse: true);
      case BidButtonState.leading:
        _pulseController.repeat();
        AppHaptics.bidConfirmed();
      case BidButtonState.outbid:
        _shakeController.forward(from: 0);
        AppHaptics.outbid();
      case BidButtonState.disabled:
        break;
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _shakeController.dispose();
    _opacityController.dispose();
    _springController.dispose();
    super.dispose();
  }

  Color get _backgroundColor => switch (widget.state) {
        BidButtonState.idle    => AppColors.gold,
        BidButtonState.loading => AppColors.gold,
        BidButtonState.leading => AppColors.emerald,
        BidButtonState.outbid  => AppColors.ember,
        BidButtonState.disabled => AppColors.mist.withValues(alpha: 0.4),
      };

  Color get _foregroundColor => switch (widget.state) {
        BidButtonState.disabled => AppColors.mist,
        _ => Colors.white,
      };

  String get _label => widget.label ?? switch (widget.state) {
        BidButtonState.idle    => 'ضع مزايدتك',
        BidButtonState.loading => 'جاري الإرسال...',
        BidButtonState.leading => 'أنت في المقدمة!',
        BidButtonState.outbid  => 'تم تجاوز مزايدتك!',
        BidButtonState.disabled => 'انتهى المزاد',
      };

  IconData? get _icon => switch (widget.state) {
        BidButtonState.leading => Icons.emoji_events_rounded,
        BidButtonState.outbid  => Icons.warning_amber_rounded,
        _ => null,
      };

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: Listenable.merge([
        _pulseScale,
        _shakeOffset,
        _opacityPulse,
        _springController,
      ]),
      builder: (context, child) {
        // Determine scale
        double scale = 1.0;
        if (widget.state == BidButtonState.leading) {
          scale = _pulseScale.value;
        }

        // Determine offset (shake)
        double dx = 0;
        if (widget.state == BidButtonState.outbid &&
            _shakeController.isAnimating) {
          dx = _shakeOffset.value;
        }

        // Determine opacity
        double opacity = 1.0;
        if (widget.state == BidButtonState.loading) {
          opacity = _opacityPulse.value;
        }

        return Transform.translate(
          offset: Offset(dx, 0),
          child: Transform.scale(
            scale: scale,
            child: Opacity(
              opacity: opacity,
              child: child,
            ),
          ),
        );
      },
      child: AnimatedContainer(
        duration: AppAnimations.state,
        curve: AppAnimations.springCurve,
        width: double.infinity,
        height: 56,
        child: Material(
          color: _backgroundColor,
          borderRadius: AppSpacing.radiusMd,
          child: InkWell(
            onTap: widget.state == BidButtonState.idle ||
                    widget.state == BidButtonState.outbid
                ? widget.onPressed
                : null,
            borderRadius: AppSpacing.radiusMd,
            child: Center(
              child: widget.state == BidButtonState.loading
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor:
                            AlwaysStoppedAnimation<Color>(Colors.white),
                      ),
                    )
                  : Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (_icon != null) ...[
                          Icon(_icon, color: _foregroundColor, size: 20),
                          const SizedBox(width: AppSpacing.xs),
                        ],
                        Text(
                          _label,
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: _foregroundColor,
                          ),
                        ),
                      ],
                    ),
            ),
          ),
        ),
      ),
    );
  }
}
