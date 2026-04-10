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
    this.timerRemaining,
    this.timerExtended = false,
    this.onExpired,
  });

  /// ISO 8601 end time string from server.
  final String? endsAt;

  /// Server-provided TTL in seconds — preferred over endsAt to avoid clock drift.
  final int? timerRemaining;

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

  // Timer digit amber flash 3× on extension
  late AnimationController _flashController;
  late Animation<Color?> _digitFlash;

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

    // Flash 3× amber on timer extension
    _flashController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900), // 3 × 300ms
    );
    _digitFlash = TweenSequence<Color?>([
      // Flash 1
      TweenSequenceItem(
        tween: ColorTween(begin: AppColors.navy, end: const Color(0xFFFBB040)),
        weight: 1,
      ),
      TweenSequenceItem(
        tween: ColorTween(begin: const Color(0xFFFBB040), end: AppColors.navy),
        weight: 1,
      ),
      // Flash 2
      TweenSequenceItem(
        tween: ColorTween(begin: AppColors.navy, end: const Color(0xFFFBB040)),
        weight: 1,
      ),
      TweenSequenceItem(
        tween: ColorTween(begin: const Color(0xFFFBB040), end: AppColors.navy),
        weight: 1,
      ),
      // Flash 3
      TweenSequenceItem(
        tween: ColorTween(begin: AppColors.navy, end: const Color(0xFFFBB040)),
        weight: 1,
      ),
      TweenSequenceItem(
        tween: ColorTween(begin: const Color(0xFFFBB040), end: AppColors.navy),
        weight: 1,
      ),
    ]).animate(_flashController);

    if (widget.timerRemaining != null) {
      _syncFromServer(widget.timerRemaining!);
    } else {
      _computeRemaining();
    }
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  @override
  void didUpdateWidget(AuctionTimer old) {
    super.didUpdateWidget(old);

    // Server TTL correction: re-sync when timerRemaining changes
    if (widget.timerRemaining != null &&
        widget.timerRemaining != old.timerRemaining) {
      _expired = false;
      _syncFromServer(widget.timerRemaining!);
    } else if (old.endsAt != widget.endsAt) {
      // Fallback: recompute when endsAt changes
      _expired = false;
      _serverSyncedAt = null;
      _serverTtl = null;
      _computeRemaining();
    }

    // Timer extended banner + amber digit flash
    if (widget.timerExtended && !old.timerExtended) {
      _bannerController.forward(from: 0);
      _flashController.forward(from: 0);
      Future.delayed(const Duration(seconds: 5), () {
        if (mounted) _bannerController.reverse();
      });
    }
  }

  /// Server-corrected epoch: set when timerRemaining arrives from server.
  DateTime? _serverSyncedAt;
  int? _serverTtl;

  void _syncFromServer(int ttl) {
    _serverTtl = ttl;
    _serverSyncedAt = DateTime.now();
    _remaining = Duration(seconds: ttl);
  }

  void _computeRemaining() {
    // Prefer server-provided TTL (avoids client ↔ server clock drift)
    if (_serverSyncedAt != null && _serverTtl != null) {
      final elapsed = DateTime.now().difference(_serverSyncedAt!);
      final left = Duration(seconds: _serverTtl!) - elapsed;
      _remaining = left.isNegative ? Duration.zero : left;
      return;
    }
    // Fallback: compute from endsAt
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
    _flashController.dispose();
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
          child: AnimatedBuilder(
            animation: _digitFlash,
            builder: (_, child) {
              // Use flash color during extension animation, else normal
              final textColor = _flashController.isAnimating
                  ? _digitFlash.value ?? _timerColor
                  : _timerColor;
              return Container(
                padding: const EdgeInsetsDirectional.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.sm,
                ),
                decoration: BoxDecoration(
                  color: _timerColor.withValues(alpha: 0.1),
                  borderRadius: AppSpacing.radiusMd,
                  border: Border.all(color: _timerColor.withValues(alpha: 0.3)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(Icons.timer_outlined, color: textColor, size: 20),
                    const SizedBox(width: AppSpacing.xs),
                    Text(
                      _formattedTime,
                      style: TextStyle(
                        fontSize: 24,
                        fontWeight: FontWeight.w700,
                        color: textColor,
                        fontFamily: 'Sora',
                        fontFeatures: const [FontFeature.tabularFigures()],
                      ),
                    ),
                  ],
                ),
              );
            },
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
            'تم تمديد الوقت!',
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
