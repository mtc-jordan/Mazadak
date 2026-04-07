import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/theme/animations.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Auction countdown timer with visual urgency cues.
///
/// SDD §7.2:
/// - Timer.periodic(1s) with server correction on bid_update
/// - Under 30s: color transitions to ember #C4420A
/// - Scale pulse 1.0→1.06 at 1.2s interval when <30s
/// - On timer_extended: bounce banner from top (spring curve), auto-dismiss 5s
class AuctionTimer extends StatefulWidget {
  const AuctionTimer({
    super.key,
    required this.endsAt,
    this.timerExtended = false,
    this.onExpired,
  });

  /// ISO 8601 end time string from server.
  final String? endsAt;

  /// Whether the timer was recently extended (anti-snipe).
  final bool timerExtended;

  /// Called once when the timer reaches zero.
  final VoidCallback? onExpired;

  @override
  State<AuctionTimer> createState() => _AuctionTimerState();
}

class _AuctionTimerState extends State<AuctionTimer>
    with TickerProviderStateMixin {
  Timer? _ticker;
  Duration _remaining = Duration.zero;
  bool _expired = false;

  // Pulse animation for <30s urgency
  late AnimationController _pulseController;
  late Animation<double> _pulseAnimation;

  // Extended banner animation
  late AnimationController _bannerController;
  late Animation<Offset> _bannerSlide;

  @override
  void initState() {
    super.initState();

    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _pulseAnimation = TweenSequence<double>([
      TweenSequenceItem(
        tween: Tween(begin: 1.0, end: 1.06)
            .chain(CurveTween(curve: Curves.easeOut)),
        weight: 50,
      ),
      TweenSequenceItem(
        tween: Tween(begin: 1.06, end: 1.0)
            .chain(CurveTween(curve: Curves.easeIn)),
        weight: 50,
      ),
    ]).animate(_pulseController);

    _bannerController = AnimationController(
      vsync: this,
      duration: AppAnimations.enter,
    );
    _bannerSlide = Tween<Offset>(
      begin: const Offset(0, -1),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _bannerController,
      // Spring-like cubic-bezier(0, 0.8, 0.3, 1)
      curve: const Cubic(0, 0.8, 0.3, 1),
    ));

    _computeRemaining();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  @override
  void didUpdateWidget(AuctionTimer old) {
    super.didUpdateWidget(old);

    // Server correction: recompute when endsAt changes
    if (old.endsAt != widget.endsAt) {
      _expired = false;
      _computeRemaining();
    }

    // Timer extended banner
    if (widget.timerExtended && !old.timerExtended) {
      _bannerController.forward(from: 0);
    }
    if (!widget.timerExtended && old.timerExtended) {
      _bannerController.reverse();
    }
  }

  void _computeRemaining() {
    if (widget.endsAt == null) {
      _remaining = Duration.zero;
      return;
    }
    final end = DateTime.tryParse(widget.endsAt!);
    if (end == null) {
      _remaining = Duration.zero;
      return;
    }
    final now = DateTime.now().toUtc();
    _remaining = end.difference(now);
    if (_remaining.isNegative) _remaining = Duration.zero;
  }

  void _tick() {
    if (_expired) return;

    _computeRemaining();

    if (_remaining <= Duration.zero && !_expired) {
      _expired = true;
      _pulseController.stop();
      widget.onExpired?.call();
    }

    // Start/stop pulse based on <30s threshold
    if (_remaining.inSeconds <= 30 && _remaining.inSeconds > 0) {
      if (!_pulseController.isAnimating) {
        _pulseController.repeat();
      }
    } else {
      if (_pulseController.isAnimating) {
        _pulseController.stop();
        _pulseController.reset();
      }
    }

    setState(() {});
  }

  @override
  void dispose() {
    _ticker?.cancel();
    _pulseController.dispose();
    _bannerController.dispose();
    super.dispose();
  }

  Color get _timerColor {
    final secs = _remaining.inSeconds;
    if (secs <= 0) return AppColors.mist;
    if (secs <= 30) return AppColors.ember;
    if (secs <= 60) return const Color(0xFFD4820A); // amber warning
    return AppColors.navy;
  }

  String get _formattedTime {
    if (_remaining <= Duration.zero) return '00:00';

    final hours = _remaining.inHours;
    final mins = _remaining.inMinutes.remainder(60);
    final secs = _remaining.inSeconds.remainder(60);

    if (hours > 0) {
      return '${hours.toString().padLeft(2, '0')}:'
          '${mins.toString().padLeft(2, '0')}:'
          '${secs.toString().padLeft(2, '0')}';
    }
    return '${mins.toString().padLeft(2, '0')}:'
        '${secs.toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        // ── Extended banner ──────────────────────────────────────
        SlideTransition(
          position: _bannerSlide,
          child: _buildExtendedBanner(),
        ),

        // ── Timer display ───────────────────────────────────────
        ScaleTransition(
          scale: _pulseAnimation,
          child: Container(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.lg,
              vertical: AppSpacing.sm,
            ),
            decoration: BoxDecoration(
              color: _timerColor.withOpacity(0.1),
              borderRadius: AppSpacing.radiusMd,
              border: Border.all(color: _timerColor.withOpacity(0.3)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.timer_outlined, color: _timerColor, size: 20),
                const SizedBox(width: AppSpacing.xs),
                Text(
                  _formattedTime,
                  style: TextStyle(
                    fontSize: 24,
                    fontWeight: FontWeight.w700,
                    color: _timerColor,
                    fontFamily: 'Sora',
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildExtendedBanner() {
    return Container(
      width: double.infinity,
      padding: AppSpacing.allSm,
      margin: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
      decoration: BoxDecoration(
        color: const Color(0xFFFBE8A0),
        borderRadius: AppSpacing.radiusMd,
      ),
      child: const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(Icons.update, size: 18, color: AppColors.gold),
          SizedBox(width: AppSpacing.xs),
          Text(
            'Extended!',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.gold,
            ),
          ),
        ],
      ),
    );
  }
}
