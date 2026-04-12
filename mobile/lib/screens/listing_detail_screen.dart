import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:go_router/go_router.dart';

import '../core/l10n/arabic_numerals.dart';
import '../core/providers/listing_detail_provider.dart';
import '../core/router.dart';
import '../core/theme/animations.dart';
import '../core/theme/colors.dart';
import '../core/theme/haptics.dart';
import '../core/theme/spacing.dart';
import 'package:intl/intl.dart' hide TextDirection;
import '../l10n/app_localizations.dart';

// ═══════════════════════════════════════════════════════════════════════
//  ListingDetailScreen
// ═══════════════════════════════════════════════════════════════════════
//
//  SliverAppBar with hero image PageView + dot indicators
//  Floating FABs: heart (AnimatedSwitcher fill) + share
//  Price block: per-digit AnimatedSwitcher on stream update
//  ATS seller card: tap expands signal bars via AnimatedSize
//  Timer countdown: Timer.periodic(1s), ember + timerPulse < 30 min
//  Watcher count: live via WebSocket broadcast
//  CTA: Watch button toggles emerald fill, Bid button: InkWell ripple
//       from tap position via GestureDetector.onTapDown
// ═══════════════════════════════════════════════════════════════════════

class ListingDetailScreen extends ConsumerStatefulWidget {
  const ListingDetailScreen({super.key, required this.listingId});
  final String listingId;

  @override
  ConsumerState<ListingDetailScreen> createState() =>
      _ListingDetailScreenState();
}

class _ListingDetailScreenState extends ConsumerState<ListingDetailScreen>
    with TickerProviderStateMixin {
  final _pageController = PageController();
  int _currentPage = 0;

  // ── Timer ────────────────────────────────────────────────────────
  Timer? _countdownTimer;
  Duration _remaining = Duration.zero;

  // ── Timer pulse (under 30 min) ───────────────────────────────────
  late AnimationController _timerPulseController;
  late Animation<double> _timerPulse;

  // ── ATS expand ───────────────────────────────────────────────────
  bool _atsExpanded = false;

  // ── Price flash on WebSocket update ──────────────────────────────
  late AnimationController _priceFlashCtrl;
  late Animation<Color?> _priceFlashColor;
  double _prevPrice = 0;

  // ── CTA slide-up entrance ─────────────────────────────────────────
  late AnimationController _ctaSlideCtrl;
  late Animation<Offset> _ctaSlide;

  @override
  void initState() {
    super.initState();

    // Price flash: amber → transparent over 600ms
    _priceFlashCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _priceFlashColor = ColorTween(
      begin: const Color(0xFFFBE8A0),
      end: Colors.transparent,
    ).animate(CurvedAnimation(parent: _priceFlashCtrl, curve: Curves.easeOut));

    // CTA slide up from bottom
    _ctaSlideCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 500),
    );
    _ctaSlide = Tween<Offset>(
      begin: const Offset(0, 0.5),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _ctaSlideCtrl, curve: Curves.easeOutCubic));
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _ctaSlideCtrl.forward();
    });

    _timerPulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _timerPulse = TweenSequence<double>([
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
    ]).animate(_timerPulseController);
  }

  @override
  void dispose() {
    _pageController.dispose();
    _countdownTimer?.cancel();
    _timerPulseController.dispose();
    _priceFlashCtrl.dispose();
    _ctaSlideCtrl.dispose();
    super.dispose();
  }

  void _startCountdown(String? endsAt) {
    _countdownTimer?.cancel();
    if (endsAt == null) return;
    final end = DateTime.tryParse(endsAt);
    if (end == null) return;

    void tick() {
      final diff = end.difference(DateTime.now().toUtc());
      if (!mounted) return;
      setState(() {
        _remaining = diff.isNegative ? Duration.zero : diff;
      });
      // Pulse when under 5 minutes
      if (_remaining.inMinutes < 5 && _remaining > Duration.zero) {
        if (!_timerPulseController.isAnimating) {
          _timerPulseController.repeat();
        }
      } else {
        if (_timerPulseController.isAnimating) {
          _timerPulseController.stop();
          _timerPulseController.reset();
        }
      }
    }

    tick();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) => tick());
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(listingDetailProvider(widget.listingId));

    if (state.isLoading) {
      return const Scaffold(
        body: Center(
          child: CircularProgressIndicator(color: AppColors.gold),
        ),
      );
    }
    if (state.error != null || state.listing == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(
          child: Text(
            state.error ?? 'خطأ في تحميل القائمة',
            style: const TextStyle(color: AppColors.ember),
          ),
        ),
      );
    }

    final listing = state.listing!;

    // Flash amber when price updates via WebSocket
    if (listing.displayPrice != _prevPrice && _prevPrice != 0) {
      _priceFlashCtrl.forward(from: 0);
    }
    _prevPrice = listing.displayPrice;

    // Start countdown if not already running
    if (_countdownTimer == null && listing.endsAt != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _startCountdown(listing.endsAt);
      });
    }

    return Scaffold(
      body: Stack(
        children: [
          CustomScrollView(
            slivers: [
              // ── Image header ────────────────────────────────────
              _buildImageHeader(listing),
              // ── Body content ────────────────────────────────────
              SliverToBoxAdapter(child: _buildBody(listing)),
            ],
          ),
          // ── Floating action buttons ─────────────────────────────
          PositionedDirectional(
            top: MediaQuery.of(context).padding.top + 340 - 28,
            end: AppSpacing.md,
            child: Row(
              children: [
                _HeartFab(
                  isWatched: listing.isWatched,
                  onTap: () {
                    HapticFeedback.lightImpact();
                    ref
                        .read(
                            listingDetailProvider(widget.listingId).notifier)
                        .toggleWatchlist();
                  },
                ),
                const SizedBox(width: AppSpacing.xs),
                _CircleFab(
                  icon: Icons.share_rounded,
                  onTap: () {
                    HapticFeedback.selectionClick();
                    Clipboard.setData(ClipboardData(
                        text: 'https://mzadak.com/listing/${widget.listingId}'));
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        content: Text(S.of(context).linkCopied,
                            style: const TextStyle(fontFamily: 'NotoKufiArabic')),
                        backgroundColor: AppColors.navy,
                        behavior: SnackBarBehavior.floating,
                        shape: RoundedRectangleBorder(
                            borderRadius: AppSpacing.radiusMd),
                        duration: const Duration(seconds: 2),
                      ),
                    );
                  },
                ),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: SlideTransition(
        position: _ctaSlide,
        child: _buildBottomCta(context, listing),
      ),
    );
  }

  // ── Image header with PageView + dot indicators ───────────────────

  SliverAppBar _buildImageHeader(ListingDetail listing) {
    return SliverAppBar(
      expandedHeight: 340,
      pinned: true,
      backgroundColor: Colors.white,
      foregroundColor: AppColors.navy,
      flexibleSpace: FlexibleSpaceBar(
        background: Stack(
          fit: StackFit.expand,
          children: [
            // PageView image gallery with hero on first image
            PageView.builder(
              controller: _pageController,
              onPageChanged: (i) => setState(() => _currentPage = i),
              itemCount: listing.imageUrls.length,
              itemBuilder: (_, i) {
                final image = CachedNetworkImage(
                  imageUrl: listing.imageUrls[i],
                  fit: BoxFit.cover,
                  placeholder: (_, __) => Container(color: AppColors.sand),
                  errorWidget: (_, __, ___) => Container(
                    color: AppColors.sand,
                    child: const Icon(Icons.image_not_supported_rounded,
                        color: AppColors.mist, size: 48),
                  ),
                );
                // Hero only on first image
                if (i == 0) {
                  return Hero(
                    tag: HeroTags.listingImage(widget.listingId),
                    child: image,
                  );
                }
                return image;
              },
            ),
            // Dot indicators
            if (listing.imageUrls.length > 1)
              Positioned(
                bottom: AppSpacing.sm,
                left: 0,
                right: 0,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: List.generate(listing.imageUrls.length, (i) {
                    return AnimatedContainer(
                      duration: AppAnimations.state,
                      width: i == _currentPage ? 16 : 5,
                      height: 5,
                      margin: const EdgeInsetsDirectional.symmetric(
                          horizontal: 3),
                      decoration: BoxDecoration(
                        color: i == _currentPage
                            ? Colors.white
                            : Colors.white54,
                        borderRadius: AppSpacing.radiusFull,
                      ),
                    );
                  }),
                ),
              ),
            // Image counter badge (e.g. "1/3")
            if (listing.imageUrls.length > 1)
              PositionedDirectional(
                top: 12,
                end: 12,
                child: Container(
                  padding: const EdgeInsetsDirectional.symmetric(
                      horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.45),
                    borderRadius: AppSpacing.radiusFull,
                  ),
                  child: Text(
                    '${_currentPage + 1}/${listing.imageUrls.length}',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 11,
                      fontFamily: 'Sora',
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ),
            // Gradient overlay at bottom for readability
            Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              height: 60,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Colors.transparent, Colors.black26],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Body content ──────────────────────────────────────────────────

  Widget _buildBody(ListingDetail listing) {
    return Padding(
      padding: AppSpacing.allMd,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Badges
          _BadgesRow(listing: listing),
          const SizedBox(height: AppSpacing.sm),

          // Title (Arabic RTL)
          Directionality(
            textDirection: TextDirection.rtl,
            child: Text(
              listing.titleAr,
              style: const TextStyle(
                fontFamily: 'NotoKufiArabic',
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: AppColors.ink,
                height: 1.3,
              ),
            ),
          ),
          if (listing.titleEn != null) ...[
            const SizedBox(height: 2),
            Text(
              listing.titleEn!,
              style: const TextStyle(
                fontSize: 14,
                color: AppColors.mist,
              ),
            ),
          ],
          const SizedBox(height: AppSpacing.md),

          // ── Price block: per-digit AnimatedSwitcher + amber flash ─
          AnimatedBuilder(
            animation: _priceFlashColor,
            builder: (_, child) => Container(
              decoration: BoxDecoration(
                color: _priceFlashColor.value,
                borderRadius: AppSpacing.radiusMd,
              ),
              child: child,
            ),
            child: _PriceBlock(
              price: listing.displayPrice,
              currency: listing.currency,
              bidCount: listing.bidCount,
              buyNowPrice: listing.buyNowPrice,
            ),
          ),

          const SizedBox(height: AppSpacing.md),

          // ── Timer countdown ──────────────────────────────────────
          if (listing.endsAt != null && _remaining > Duration.zero)
            _buildTimer(),

          const SizedBox(height: AppSpacing.sm),

          // ── Watcher count with live pulsing dot ──────────────────
          if (listing.watcherCount > 0)
            Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.md),
              child: Row(
                children: [
                  if (listing.isLive) ...[
                    _PulsingDot(color: AppColors.emerald, size: 8),
                    const SizedBox(width: 6),
                  ] else ...[
                    const Icon(Icons.visibility_rounded,
                        size: 16, color: AppColors.mist),
                    const SizedBox(width: AppSpacing.xxs),
                  ],
                  Text(
                    '${ArabicNumerals.formatNumber(listing.watcherCount)} يشاهدون الآن',
                    style: TextStyle(
                      fontSize: 13,
                      color: listing.isLive ? AppColors.emerald : AppColors.mist,
                      fontWeight: listing.isLive ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ],
              ),
            ),

          const Divider(color: AppColors.sand),
          const SizedBox(height: AppSpacing.md),

          // ── ATS seller card (tap expands) ────────────────────────
          _AtsSellerCard(
            seller: listing.seller,
            isExpanded: _atsExpanded,
            onTap: () => setState(() => _atsExpanded = !_atsExpanded),
          ),

          const SizedBox(height: AppSpacing.lg),
          const Divider(color: AppColors.sand),
          const SizedBox(height: AppSpacing.md),

          // ── Specs grid (6 cells, 2 columns) ─────────────────────
          _SpecsGrid(listing: listing),

          const SizedBox(height: AppSpacing.lg),

          // ── Collapsible description ─────────────────────────────
          _CollapsibleDescription(text: listing.descriptionAr),

          // Bottom padding for CTA bar
          const SizedBox(height: 100),
        ],
      ),
    );
  }

  // ── Timer with pulse ──────────────────────────────────────────────

  Widget _buildTimer() {
    final h = _remaining.inHours;
    final m = _remaining.inMinutes.remainder(60);
    final s = _remaining.inSeconds.remainder(60);
    final text = h > 0
        ? '${_pad(h)}:${_pad(m)}:${_pad(s)}'
        : '${_pad(m)}:${_pad(s)}';

    final isUrgent = _remaining.inMinutes < 5;
    final color = isUrgent ? AppColors.ember : AppColors.navy;

    Widget timer = Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: AppSpacing.radiusMd,
        border: Border.all(color: color.withValues(alpha: 0.2)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.timer_rounded, color: color, size: 18),
          const SizedBox(width: AppSpacing.xs),
          Text(
            text,
            textDirection: TextDirection.ltr,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w700,
              color: color,
              fontFamily: 'Sora',
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ],
      ),
    );

    if (isUrgent) {
      timer = AnimatedBuilder(
        animation: _timerPulse,
        builder: (_, child) => Transform.scale(
          scale: _timerPulse.value,
          child: child,
        ),
        child: timer,
      );
    }

    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
      child: timer,
    );
  }

  String _pad(int n) => n.toString().padLeft(2, '0');

  // ── Bottom CTA bar ────────────────────────────────────────────────

  Widget _buildBottomCta(BuildContext context, ListingDetail listing) {
    return Container(
      padding: EdgeInsetsDirectional.only(
        start: AppSpacing.md,
        end: AppSpacing.md,
        top: AppSpacing.sm,
        bottom: MediaQuery.of(context).viewPadding.bottom + AppSpacing.sm,
      ),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: AppColors.sand)),
      ),
      child: Row(
        children: [
          // Watch button: toggles emerald fill
          _WatchToggleButton(
            isWatched: listing.isWatched,
            onTap: () {
              HapticFeedback.lightImpact();
              ref
                  .read(listingDetailProvider(widget.listingId).notifier)
                  .toggleWatchlist();
            },
          ),
          const SizedBox(width: AppSpacing.sm),

          // Bid button: InkWell ripple from tap position
          Expanded(child: _BidCtaButton(listing: listing)),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Heart FAB with AnimatedSwitcher for fill state
// ═══════════════════════════════════════════════════════════════════════

class _HeartFab extends StatefulWidget {
  const _HeartFab({required this.isWatched, required this.onTap});
  final bool isWatched;
  final VoidCallback onTap;

  @override
  State<_HeartFab> createState() => _HeartFabState();
}

class _HeartFabState extends State<_HeartFab>
    with SingleTickerProviderStateMixin {
  late AnimationController _heartCtrl;
  late Animation<double> _heartScale;

  @override
  void initState() {
    super.initState();
    _heartCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _heartScale = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 1.0, end: 1.35), weight: 30),
      TweenSequenceItem(tween: Tween(begin: 1.35, end: 0.9), weight: 35),
      TweenSequenceItem(tween: Tween(begin: 0.9, end: 1.0), weight: 35),
    ]).animate(CurvedAnimation(parent: _heartCtrl, curve: Curves.easeOut));
  }

  @override
  void didUpdateWidget(covariant _HeartFab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.isWatched != oldWidget.isWatched) {
      _heartCtrl.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _heartCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: widget.onTap,
      child: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: Colors.white,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: AppColors.navy.withValues(alpha: 0.12),
              blurRadius: 8,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: ScaleTransition(
          scale: _heartScale,
          child: AnimatedSwitcher(
            duration: const Duration(milliseconds: 300),
            transitionBuilder: (child, anim) {
              return FadeTransition(opacity: anim, child: child);
            },
            child: widget.isWatched
                ? SvgPicture.asset(
                    'assets/icons/heart_filled.svg',
                    key: const ValueKey('filled'),
                    width: 22,
                    height: 22,
                    colorFilter: const ColorFilter.mode(
                        AppColors.ember, BlendMode.srcIn),
                  )
                : SvgPicture.asset(
                    'assets/icons/heart_outline.svg',
                    key: const ValueKey('outline'),
                    width: 22,
                    height: 22,
                    colorFilter: const ColorFilter.mode(
                        AppColors.navy, BlendMode.srcIn),
                  ),
          ),
        ),
      ),
    );
  }
}

class _CircleFab extends StatelessWidget {
  const _CircleFab({required this.icon, required this.onTap});
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: Colors.white,
          shape: BoxShape.circle,
          boxShadow: [
            BoxShadow(
              color: AppColors.navy.withValues(alpha: 0.12),
              blurRadius: 8,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Icon(icon, color: AppColors.navy, size: 22),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Price block: per-digit AnimatedSwitcher
// ═══════════════════════════════════════════════════════════════════════

class _PriceBlock extends StatelessWidget {
  const _PriceBlock({
    required this.price,
    required this.currency,
    required this.bidCount,
    this.buyNowPrice,
  });

  final double price;
  final String currency;
  final int bidCount;
  final double? buyNowPrice;

  @override
  Widget build(BuildContext context) {
    final formatted =
        ArabicNumerals.formatCurrencyEn(price, currency);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Per-digit animated price — force LTR to prevent RTL reversal
        Row(
          children: [
            Directionality(
              textDirection: TextDirection.ltr,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: formatted.split('').asMap().entries.map((entry) {
                  final i = entry.key;
                  final char = entry.value;
                  return AnimatedSwitcher(
                    duration: const Duration(milliseconds: 300),
                    transitionBuilder: (child, anim) {
                      return SlideTransition(
                        position: Tween<Offset>(
                          begin: const Offset(0, -0.5),
                          end: Offset.zero,
                        ).animate(CurvedAnimation(
                          parent: anim,
                          curve: Curves.easeOutCubic,
                        )),
                        child: FadeTransition(opacity: anim, child: child),
                      );
                    },
                    child: Text(
                      char,
                      key: ValueKey('$char-$i'),
                      style: const TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                        fontFamily: 'Sora',
                      ),
                    ),
                  );
                }).toList(),
              ),
            ),
            const Spacer(),
            Text(
              '${ArabicNumerals.formatNumber(bidCount)} مزايدة',
              style: const TextStyle(fontSize: 13, color: AppColors.mist),
            ),
          ],
        ),
        if (buyNowPrice != null) ...[
          const SizedBox(height: AppSpacing.xxs),
          Row(
            children: [
              const Icon(Icons.bolt_rounded, size: 14, color: AppColors.gold),
              const SizedBox(width: 4),
              Text(
                'شراء فوري: ${ArabicNumerals.formatCurrency(buyNowPrice!, currency)}',
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.gold,
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  ATS Seller card — tap expands full signal bar breakdown
// ═══════════════════════════════════════════════════════════════════════

class _AtsSellerCard extends StatefulWidget {
  const _AtsSellerCard({
    required this.seller,
    required this.isExpanded,
    required this.onTap,
  });

  final SellerSummary seller;
  final bool isExpanded;
  final VoidCallback onTap;

  @override
  State<_AtsSellerCard> createState() => _AtsSellerCardState();
}

class _AtsSellerCardState extends State<_AtsSellerCard>
    with SingleTickerProviderStateMixin {
  late AnimationController _atsExpandCtrl;
  late Animation<double> _atsExpand;

  @override
  void initState() {
    super.initState();
    _atsExpandCtrl = AnimationController(
      vsync: this,
      duration: AppAnimations.enter,
    );
    _atsExpand = CurvedAnimation(
      parent: _atsExpandCtrl,
      curve: AppAnimations.enterCurve,
    );
    if (widget.isExpanded) _atsExpandCtrl.value = 1.0;
  }

  @override
  void didUpdateWidget(covariant _AtsSellerCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.isExpanded != oldWidget.isExpanded) {
      widget.isExpanded ? _atsExpandCtrl.forward() : _atsExpandCtrl.reverse();
    }
  }

  @override
  void dispose() {
    _atsExpandCtrl.dispose();
    super.dispose();
  }

  Color get _tierColor => switch (widget.seller.atsTier) {
        'elite' => AppColors.emerald,
        'pro' => AppColors.gold,
        'trusted' => AppColors.navy,
        _ => AppColors.mist,
      };

  String get _tierLabel => switch (widget.seller.atsTier) {
        'elite' => 'نخبة',
        'pro' => 'محترف',
        'trusted' => 'موثوق',
        _ => 'مبتدئ',
      };

  IconData get _tierIcon => switch (widget.seller.atsTier) {
        'elite' => Icons.diamond_rounded,
        'pro' => Icons.workspace_premium_rounded,
        'trusted' => Icons.verified_user_rounded,
        _ => Icons.person_rounded,
      };

  @override
  Widget build(BuildContext context) {
    final seller = widget.seller;
    return GestureDetector(
      onTap: widget.onTap,
      child: Container(
        padding: AppSpacing.allMd,
        decoration: BoxDecoration(
          color: AppColors.cream,
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(color: AppColors.sand),
        ),
        child: Column(
          children: [
            // ── Seller header row ───────────────────────────────
            Row(
              children: [
                // Avatar
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: _tierColor.withValues(alpha: 0.12),
                    shape: BoxShape.circle,
                  ),
                  child: seller.avatarUrl != null
                      ? ClipOval(
                          child: CachedNetworkImage(
                            imageUrl: seller.avatarUrl!,
                            fit: BoxFit.cover,
                          ),
                        )
                      : Icon(Icons.person, color: _tierColor, size: 24),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        seller.nameAr,
                        style: const TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Row(
                        children: [
                          Icon(_tierIcon, color: _tierColor, size: 14),
                          const SizedBox(width: 4),
                          Text(
                            _tierLabel,
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: _tierColor,
                            ),
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            '• ${seller.listingsCount} قائمة',
                            style: const TextStyle(
                                fontSize: 12, color: AppColors.mist),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                // ATS score pill
                Container(
                  padding: const EdgeInsetsDirectional.symmetric(
                    horizontal: AppSpacing.sm,
                    vertical: AppSpacing.xxs,
                  ),
                  decoration: BoxDecoration(
                    color: _tierColor.withValues(alpha: 0.1),
                    borderRadius: AppSpacing.radiusMd,
                  ),
                  child: Text(
                    '${seller.atsScore}',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w800,
                      color: _tierColor,
                      fontFamily: 'Sora',
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.xxs),
                AnimatedRotation(
                  turns: widget.isExpanded ? 0.5 : 0,
                  duration: AppAnimations.state,
                  child: const Icon(Icons.keyboard_arrow_down_rounded,
                      color: AppColors.mist, size: 20),
                ),
              ],
            ),

            // ── Expandable signal bar breakdown (SizeTransition) ─
            SizeTransition(
              sizeFactor: _atsExpand,
              axisAlignment: -1.0,
              child: _AtsSignalBars(seller: seller, tierColor: _tierColor),
            ),
          ],
        ),
      ),
    );
  }
}

/// Full ATS signal bar breakdown — shown when user taps the seller card.
/// Bars animate from 0 → target width over 1.2s with 80ms stagger.
class _AtsSignalBars extends StatefulWidget {
  const _AtsSignalBars({required this.seller, required this.tierColor});
  final SellerSummary seller;
  final Color tierColor;

  @override
  State<_AtsSignalBars> createState() => _AtsSignalBarsState();
}

class _AtsSignalBarsState extends State<_AtsSignalBars>
    with TickerProviderStateMixin {
  final List<AnimationController> _controllers = [];
  final List<Animation<double>> _animations = [];

  // 6 signal bars per SDD spec
  static const _signals = [
    ('التحقق من الهوية', Icons.verified_user_rounded, 1.0),
    ('نسبة الإتمام', Icons.check_circle_rounded, 0.0),
    ('سرعة الاستجابة', Icons.speed_rounded, 0.0),
    ('التقييمات', Icons.star_rounded, 0.0),
    ('جودة القوائم', Icons.high_quality_rounded, 0.0),
    ('سجل خالٍ من النزاعات', Icons.shield_rounded, 1.0),
  ];

  @override
  void initState() {
    super.initState();
    // Compute approximate bar values from seller data (6 bars)
    final values = [
      1.0, // identity verified (always 1 if they have ATS)
      widget.seller.completionRate,
      (widget.seller.atsScore / 1000).clamp(0.0, 1.0), // proxy for speed
      (widget.seller.atsScore / 1000).clamp(0.0, 1.0), // proxy for ratings
      (widget.seller.atsScore / 800).clamp(0.0, 1.0),  // proxy for quality
      1.0 - (widget.seller.atsScore < 300 ? 0.5 : 0.0), // dispute-free
    ];

    for (var i = 0; i < _signals.length; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 1200),
      );
      final anim = Tween<double>(begin: 0, end: values[i]).animate(
        CurvedAnimation(parent: controller, curve: Curves.easeOutCubic),
      );
      _controllers.add(controller);
      _animations.add(anim);
    }

    _staggerBars();
  }

  Future<void> _staggerBars() async {
    for (var i = 0; i < _controllers.length; i++) {
      if (!mounted) return;
      _controllers[i].forward();
      if (i < _controllers.length - 1) {
        await Future.delayed(const Duration(milliseconds: 80));
      }
    }
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(top: AppSpacing.md),
      child: Column(
        children: List.generate(_signals.length, (i) {
          final (label, icon, _) = _signals[i];
          return Padding(
            padding: EdgeInsetsDirectional.only(
              bottom: i < _signals.length - 1 ? AppSpacing.sm : 0,
            ),
            child: AnimatedBuilder(
              animation: _animations[i],
              builder: (_, __) {
                final value = _animations[i].value;
                return _SignalBarRow(
                  label: label,
                  icon: icon,
                  value: value,
                  color: _barColor(value),
                );
              },
            ),
          );
        }),
      ),
    );
  }

  Color _barColor(double value) {
    if (value >= 0.8) return AppColors.emerald;
    if (value >= 0.5) return AppColors.gold;
    if (value > 0) return const Color(0xFF4A9BD9); // sky
    return AppColors.sand;
  }
}

class _SignalBarRow extends StatelessWidget {
  const _SignalBarRow({
    required this.label,
    required this.icon,
    required this.value,
    required this.color,
  });

  final String label;
  final IconData icon;
  final double value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(icon, size: 14, color: AppColors.mist),
            const SizedBox(width: AppSpacing.xs),
            Text(label,
                style:
                    const TextStyle(fontSize: 12, color: AppColors.ink)),
            const Spacer(),
            Text(
              '${(value * 100).round()}%',
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: color,
                fontFamily: 'Sora',
              ),
            ),
          ],
        ),
        const SizedBox(height: 3),
        ClipRRect(
          borderRadius: AppSpacing.radiusFull,
          child: SizedBox(
            height: 6,
            child: Stack(
              children: [
                Container(width: double.infinity, color: AppColors.sand),
                FractionallySizedBox(
                  widthFactor: value.clamp(0, 1),
                  child: Container(
                    decoration: BoxDecoration(
                      color: color,
                      borderRadius: AppSpacing.radiusFull,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Badges row
// ═══════════════════════════════════════════════════════════════════════

class _BadgesRow extends StatelessWidget {
  const _BadgesRow({required this.listing});
  final ListingDetail listing;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppSpacing.xs,
      runSpacing: AppSpacing.xxs,
      children: [
        if (listing.isLive)
          _Badge('مباشر', AppColors.ember, Icons.circle, iconSize: 6),
        if (listing.isCertified)
          _Badge('موثّق', AppColors.emerald, Icons.verified_rounded),
        if (listing.buyNowPrice != null)
          _Badge('شراء فوري', AppColors.gold, Icons.bolt_rounded),
        if (listing.isCharity)
          _Badge('خيري', const Color(0xFF0D8A72), Icons.favorite_rounded),
        if (listing.isSnapToList)
          _Badge(
              'Snap-to-List', AppColors.navy, Icons.auto_awesome_rounded),
      ],
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge(this.label, this.color, this.icon, {this.iconSize = 10});
  final String label;
  final Color color;
  final IconData icon;
  final double iconSize;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding:
          const EdgeInsetsDirectional.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, color: color, size: iconSize),
          const SizedBox(width: 4),
          Text(label,
              style: TextStyle(
                  fontSize: 11, fontWeight: FontWeight.w600, color: color)),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Detail row + condition chip
// ═══════════════════════════════════════════════════════════════════════

class _ConditionChip extends StatelessWidget {
  const _ConditionChip({required this.condition});
  final String condition;

  Color get _color {
    final c = condition.toLowerCase();
    if (c.contains('new') || c.contains('جديد')) return AppColors.emerald;
    if (c.contains('like') || c.contains('ممتاز')) return const Color(0xFF30A06A);
    if (c.contains('good') || c.contains('جيد')) return AppColors.gold;
    return AppColors.mist;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding:
          const EdgeInsetsDirectional.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: _color.withValues(alpha: 0.12),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Text(
        condition,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: _color,
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Watch toggle button (bottom CTA)
// ═══════════════════════════════════════════════════════════════════════

class _WatchToggleButton extends StatelessWidget {
  const _WatchToggleButton({required this.isWatched, required this.onTap});
  final bool isWatched;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: AppAnimations.state,
        curve: AppAnimations.enterCurve,
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          color: isWatched ? AppColors.emerald : Colors.white,
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(
            color: isWatched ? AppColors.emerald : AppColors.sand,
          ),
        ),
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          child: Icon(
            isWatched ? Icons.visibility : Icons.visibility_outlined,
            key: ValueKey(isWatched),
            color: isWatched ? Colors.white : AppColors.mist,
            size: 22,
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Bid CTA button: InkWell ripple from touch position
// ═══════════════════════════════════════════════════════════════════════

class _BidCtaButton extends StatefulWidget {
  const _BidCtaButton({required this.listing});
  final ListingDetail listing;

  @override
  State<_BidCtaButton> createState() => _BidCtaButtonState();
}

class _BidCtaButtonState extends State<_BidCtaButton> {
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: Material(
        color: AppColors.gold,
        borderRadius: AppSpacing.radiusMd,
        child: InkWell(
          onTap: () {
            AppHaptics.bidTap();
            final id = widget.listing.auctionId;
            if (id != null) {
              context.push('/auction/$id');
            }
          },
          borderRadius: AppSpacing.radiusMd,
          splashFactory: InkRipple.splashFactory,
          child: const Center(
            child: Text(
              'ضع مزايدتك',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Pulsing dot indicator (live viewers)
// ═══════════════════════════════════════════════════════════════════════

class _PulsingDot extends StatefulWidget {
  const _PulsingDot({required this.color, this.size = 8});
  final Color color;
  final double size;

  @override
  State<_PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<_PulsingDot>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;
  late Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
    _opacity = Tween<double>(begin: 0.4, end: 1.0).animate(
      CurvedAnimation(parent: _ctrl, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _opacity,
      child: Container(
        width: widget.size,
        height: widget.size,
        decoration: BoxDecoration(
          color: widget.color,
          shape: BoxShape.circle,
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Specs grid — 2-column, 6 cells
// ═══════════════════════════════════════════════════════════════════════

class _SpecsGrid extends StatelessWidget {
  const _SpecsGrid({required this.listing});
  final ListingDetail listing;

  @override
  Widget build(BuildContext context) {
    final createdDate = DateTime.tryParse(listing.createdAt);
    final dateStr = createdDate != null
        ? DateFormat.yMMMd('ar').format(createdDate)
        : '';

    final location = [
      if (listing.locationCity != null) listing.locationCity,
      if (listing.locationCountry != null) listing.locationCountry,
    ].join('، ');

    final l = S.of(context);
    final specs = [
      _SpecItem(
        icon: Icons.category_rounded,
        label: l.categoryLabel,
        value: listing.category,
      ),
      _SpecItem(
        icon: Icons.star_rounded,
        label: l.conditionLabel,
        value: listing.condition,
        chipColor: _conditionColor(listing.condition),
      ),
      _SpecItem(
        icon: Icons.location_on_rounded,
        label: l.locationLabel,
        value: location.isNotEmpty ? location : '—',
      ),
      _SpecItem(
        icon: Icons.trending_up_rounded,
        label: l.minBidLabel,
        value: ArabicNumerals.formatCurrencyEn(
            listing.minIncrement, listing.currency),
      ),
      _SpecItem(
        icon: Icons.visibility_rounded,
        label: l.viewsLabel,
        value: ArabicNumerals.formatNumber(listing.viewCount),
      ),
      _SpecItem(
        icon: Icons.calendar_today_rounded,
        label: l.publishedDateLabel,
        value: dateStr.isNotEmpty ? dateStr : '—',
      ),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'التفاصيل',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: specs.map((spec) {
            return SizedBox(
              width: (MediaQuery.of(context).size.width - AppSpacing.md * 2 - AppSpacing.sm) / 2,
              child: Container(
                padding: AppSpacing.allSm,
                decoration: BoxDecoration(
                  color: AppColors.cream,
                  borderRadius: AppSpacing.radiusSm,
                  border: Border.all(color: AppColors.sand),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(spec.icon, size: 14, color: AppColors.mist),
                        const SizedBox(width: 4),
                        Text(
                          spec.label,
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.mist,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    if (spec.chipColor != null)
                      _ConditionChip(condition: spec.value)
                    else
                      Text(
                        spec.value,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                  ],
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  static Color? _conditionColor(String condition) {
    final c = condition.toLowerCase();
    if (c.contains('new') || c.contains('جديد')) return AppColors.emerald;
    if (c.contains('like') || c.contains('ممتاز')) return const Color(0xFF30A06A);
    if (c.contains('good') || c.contains('جيد')) return AppColors.gold;
    return null;
  }
}

class _SpecItem {
  const _SpecItem({
    required this.icon,
    required this.label,
    required this.value,
    this.chipColor,
  });
  final IconData icon;
  final String label;
  final String value;
  final Color? chipColor;
}

// ═══════════════════════════════════════════════════════════════════════
//  Collapsible description
// ═══════════════════════════════════════════════════════════════════════

class _CollapsibleDescription extends StatefulWidget {
  const _CollapsibleDescription({required this.text});
  final String text;

  @override
  State<_CollapsibleDescription> createState() =>
      _CollapsibleDescriptionState();
}

class _CollapsibleDescriptionState extends State<_CollapsibleDescription> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'الوصف',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.xs),
        AnimatedCrossFade(
          firstChild: Text(
            widget.text,
            maxLines: 4,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(
              fontSize: 14,
              color: AppColors.ink,
              height: 1.6,
            ),
          ),
          secondChild: Text(
            widget.text,
            style: const TextStyle(
              fontSize: 14,
              color: AppColors.ink,
              height: 1.6,
            ),
          ),
          crossFadeState:
              _expanded ? CrossFadeState.showSecond : CrossFadeState.showFirst,
          duration: AppAnimations.state,
        ),
        if (widget.text.length > 120)
          GestureDetector(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsetsDirectional.only(top: AppSpacing.xs),
              child: Text(
                _expanded ? 'عرض أقل' : 'عرض المزيد',
                style: const TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: AppColors.gold,
                ),
              ),
            ),
          ),
      ],
    );
  }
}
