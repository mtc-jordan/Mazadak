import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../core/l10n/arabic_numerals.dart';
import '../core/providers/listings_provider.dart';
import '../core/router.dart';
import '../core/theme/animations.dart';
import '../core/theme/colors.dart';
import '../core/theme/spacing.dart';

/// Listing card for home feed and search results.
///
/// Visual spec:
/// - Image aspect 16:9, rounded corners 12px, flat design (elevation 0)
/// - Overlay badges: LIVE (red), CERTIFIED (green), BIN (gold), CHARITY (teal)
/// - Timer: red pulsing countdown, pulse scale 1.0→1.04 every 1.2s
/// - Price: Sora 16sp/700 navy
/// - Bid count: caption mist
///
/// Interactions:
/// - onTap: scale(0.97) in 120ms then spring back
/// - onLongPress: HapticFeedback.mediumImpact + bottom sheet context menu
/// - Watchlist: SVG heart with fill animation via TweenAnimationBuilder
///
/// Hero: wraps image in Hero(tag: HeroTags.listingImage(id)) for
/// Home → Listing detail transition.
class ListingCard extends StatefulWidget {
  const ListingCard({
    super.key,
    required this.listing,
    this.onTap,
    this.onLongPress,
    this.onWatchlistToggle,
  });

  final ListingSummary listing;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;
  final ValueChanged<bool>? onWatchlistToggle;

  @override
  State<ListingCard> createState() => _ListingCardState();
}

class _ListingCardState extends State<ListingCard>
    with TickerProviderStateMixin {
  // ── Tap scale animation ─────────────────────────────────────────
  late AnimationController _scaleController;
  late Animation<double> _scaleAnimation;

  // ── Timer pulse (LIVE cards only) ───────────────────────────────
  AnimationController? _pulseController;
  Animation<double>? _pulseScale;

  // ── Watchlist state ─────────────────────────────────────────────
  late bool _isWatched;

  // ── Countdown ───────────────────────────────────────────────────
  Timer? _countdownTimer;
  Duration _remaining = Duration.zero;

  @override
  void initState() {
    super.initState();
    _isWatched = widget.listing.isWatched;

    // Tap scale: 0.97 in 120ms then spring back
    _scaleController = AnimationController(
      vsync: this,
      duration: AppAnimations.micro,
      reverseDuration: const Duration(milliseconds: 200),
    );
    _scaleAnimation = Tween<double>(begin: 1.0, end: 0.97).animate(
      CurvedAnimation(
        parent: _scaleController,
        curve: Curves.easeOut,
        reverseCurve: AppAnimations.springCurve,
      ),
    );

    // Timer pulse for LIVE cards
    if (widget.listing.isLive && widget.listing.endsAt != null) {
      _setupPulse();
      _setupCountdown();
    }
  }

  void _setupPulse() {
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
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
    ]).animate(_pulseController!);
    _pulseController!.repeat();
  }

  void _setupCountdown() {
    final endsAt = DateTime.tryParse(widget.listing.endsAt!);
    if (endsAt == null) return;
    _updateRemaining(endsAt);
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      _updateRemaining(endsAt);
    });
  }

  void _updateRemaining(DateTime endsAt) {
    final now = DateTime.now().toUtc();
    final diff = endsAt.difference(now);
    if (mounted) {
      setState(() {
        _remaining = diff.isNegative ? Duration.zero : diff;
      });
    }
  }

  @override
  void didUpdateWidget(ListingCard old) {
    super.didUpdateWidget(old);
    if (old.listing.isWatched != widget.listing.isWatched) {
      _isWatched = widget.listing.isWatched;
    }
  }

  @override
  void dispose() {
    _scaleController.dispose();
    _pulseController?.dispose();
    _countdownTimer?.cancel();
    super.dispose();
  }

  void _handleTapDown(TapDownDetails _) {
    _scaleController.forward();
  }

  void _handleTapUp(TapUpDetails _) {
    _scaleController.reverse();
    widget.onTap?.call();
  }

  void _handleTapCancel() {
    _scaleController.reverse();
  }

  void _handleLongPress() {
    HapticFeedback.mediumImpact();
    _scaleController.reverse();
    widget.onLongPress?.call();
  }

  void _toggleWatchlist() {
    setState(() => _isWatched = !_isWatched);
    widget.onWatchlistToggle?.call(_isWatched);
  }

  @override
  Widget build(BuildContext context) {
    final listing = widget.listing;

    return AnimatedBuilder(
      animation: _scaleAnimation,
      builder: (context, child) {
        return Transform.scale(
          scale: _scaleAnimation.value,
          child: child,
        );
      },
      child: GestureDetector(
        onTapDown: _handleTapDown,
        onTapUp: _handleTapUp,
        onTapCancel: _handleTapCancel,
        onLongPress: _handleLongPress,
        child: Container(
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.sand, width: 1),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── Image with badges + watchlist ────────────────────
              _buildImageSection(listing),

              // ── Info section ─────────────────────────────────────
              Padding(
                padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Title
                    Text(
                      listing.titleAr,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w500,
                        color: AppColors.ink,
                        height: 1.3,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xxs),

                    // Price
                    Text(
                      ArabicNumerals.formatCurrency(
                        listing.displayPrice,
                        listing.currency,
                      ),
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                        fontFamily: 'Sora',
                      ),
                    ),
                    const SizedBox(height: AppSpacing.xxs),

                    // Bid count
                    Text(
                      '${ArabicNumerals.formatNumber(listing.bidCount)} مزايدة',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: AppColors.mist,
                        letterSpacing: 0.2,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildImageSection(ListingSummary listing) {
    return AspectRatio(
      aspectRatio: 16 / 9,
      child: Stack(
        fit: StackFit.expand,
        children: [
          // Image with Hero for route transition
          Hero(
            tag: HeroTags.listingImage(listing.id),
            child: CachedNetworkImage(
              imageUrl: listing.imageUrl,
              fit: BoxFit.cover,
              placeholder: (_, __) => Container(color: AppColors.sand),
              errorWidget: (_, __, ___) => Container(
                color: AppColors.sand,
                child: const Icon(Icons.image_not_supported_rounded,
                    color: AppColors.mist, size: 32),
              ),
            ),
          ),

          // ── Overlay badges (top-start) ────────────────────────
          PositionedDirectional(
            top: AppSpacing.xs,
            start: AppSpacing.xs,
            child: Wrap(
              spacing: AppSpacing.xxs,
              runSpacing: AppSpacing.xxs,
              children: [
                if (listing.isLive)
                  _Badge(label: 'مباشر', color: AppColors.ember, icon: Icons.circle, iconSize: 6),
                if (listing.isCertified)
                  _Badge(label: 'موثّق', color: AppColors.emerald, icon: Icons.verified_rounded),
                if (listing.buyNowPrice != null)
                  _Badge(label: 'شراء فوري', color: AppColors.gold, icon: Icons.bolt_rounded),
                if (listing.isCharity)
                  _Badge(label: 'خيري', color: const Color(0xFF0D8A72), icon: Icons.favorite_rounded),
              ],
            ),
          ),

          // ── Countdown timer (bottom-start, LIVE only) ─────────
          if (listing.isLive && _remaining > Duration.zero)
            PositionedDirectional(
              bottom: AppSpacing.xs,
              start: AppSpacing.xs,
              child: _buildTimer(),
            ),

          // ── Watchlist heart (top-end) ─────────────────────────
          PositionedDirectional(
            top: AppSpacing.xs,
            end: AppSpacing.xs,
            child: _WatchlistHeart(
              isWatched: _isWatched,
              onTap: _toggleWatchlist,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTimer() {
    final hours = _remaining.inHours;
    final minutes = _remaining.inMinutes.remainder(60);
    final seconds = _remaining.inSeconds.remainder(60);

    final text = hours > 0
        ? '${_pad(hours)}:${_pad(minutes)}:${_pad(seconds)}'
        : '${_pad(minutes)}:${_pad(seconds)}';

    Widget timer = Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.xs,
        vertical: AppSpacing.xxs,
      ),
      decoration: BoxDecoration(
        color: AppColors.ember.withOpacity(0.9),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.timer_rounded, color: Colors.white, size: 12),
          const SizedBox(width: 3),
          Text(
            text,
            textDirection: TextDirection.ltr,
            style: const TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w700,
              color: Colors.white,
              fontFamily: 'Sora',
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );

    // Pulse scale 1.0→1.04 when live
    if (_pulseScale != null) {
      timer = AnimatedBuilder(
        animation: _pulseScale!,
        builder: (_, child) => Transform.scale(
          scale: _pulseScale!.value,
          child: child,
        ),
        child: timer,
      );
    }

    return timer;
  }

  String _pad(int n) => n.toString().padLeft(2, '0');
}

// ── Badge widget ──────────────────────────────────────────────────────

class _Badge extends StatelessWidget {
  const _Badge({
    required this.label,
    required this.color,
    this.icon,
    this.iconSize = 10,
  });

  final String label;
  final Color color;
  final IconData? icon;
  final double iconSize;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: 6,
        vertical: 3,
      ),
      decoration: BoxDecoration(
        color: color.withOpacity(0.9),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, color: Colors.white, size: iconSize),
            const SizedBox(width: 3),
          ],
          Text(
            label,
            style: const TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: Colors.white,
              letterSpacing: 0.3,
            ),
          ),
        ],
      ),
    );
  }
}

// ── Watchlist heart with SVG + fill animation ─────────────────────────

class _WatchlistHeart extends StatelessWidget {
  const _WatchlistHeart({
    required this.isWatched,
    required this.onTap,
  });

  final bool isWatched;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () {
        HapticFeedback.lightImpact();
        onTap();
      },
      child: Container(
        width: 32,
        height: 32,
        decoration: BoxDecoration(
          color: Colors.black.withOpacity(0.35),
          shape: BoxShape.circle,
        ),
        child: Center(
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: 0, end: isWatched ? 1.0 : 0.0),
            duration: const Duration(milliseconds: 300),
            curve: Curves.easeOutBack, // overshoot for scale(0)→1.3→1
            builder: (context, value, _) {
              // scale(0)→(1.3)→(1): when toggling ON, icon starts tiny
              // and overshoots. Curves.easeOutBack provides the 1.3 peak.
              // When toggling OFF, value goes 1→0 so icon shrinks.
              final double scale;
              if (isWatched) {
                // Entering watched: 0→1 with easeOutBack overshoot
                scale = value.clamp(0.0, 1.5);
              } else {
                // Leaving watched: shrink 1→0.8 (outline stays visible)
                scale = 0.8 + value * 0.2;
              }

              // Red fill sweep: color lerps white → ember as value → 1
              final color = Color.lerp(Colors.white, AppColors.ember, value)!;

              return Transform.scale(
                scale: scale,
                child: SvgPicture.asset(
                  value > 0.5
                      ? 'assets/icons/heart_filled.svg'
                      : 'assets/icons/heart_outline.svg',
                  width: 18,
                  height: 18,
                  colorFilter: ColorFilter.mode(color, BlendMode.srcIn),
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}
