import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mzadak/l10n/app_localizations.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/auction_provider.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/haptics.dart';
import '../../core/theme/spacing.dart';
import 'widgets/auction_timer.dart';
import 'widgets/bid_button.dart';
import 'widgets/bid_history_feed.dart';
import 'widgets/bid_input_sheet.dart';
import 'widgets/connection_status_banner.dart';
import 'widgets/count_up_text.dart';
import 'widgets/live_price_display.dart';

/// AuctionRoomScreen — the most important screen in the app.
///
/// SDD §7.2: Composes all auction components with premium visual layout:
/// 1. ConnectionStatusBanner (top, overlay)
/// 2. Listing info header (thumbnail + title)
/// 3. AuctionTimer (countdown with urgency cues)
/// 4. LivePriceDisplay (per-digit animation, amber flash, entry count-up)
/// 5. Stats row (watchers, bid count, extensions)
/// 6. Quick bid chips (preset increments)
/// 7. BidHistoryFeed (animated list with slide-in, staggered entry)
/// 8. BidButton (5 states with spring transitions)
///
/// Entry animations:
/// - Price counts up from 0 → current value (800ms)
/// - Bid history staggers in from bottom (30ms per row)
/// - Stats use CountUpInt
///
/// Wired to auctionProvider(id) for real-time WebSocket state.
/// Optimistic bid: shows pending immediately, rolls back after 3s if no confirm.
class AuctionRoomScreen extends ConsumerStatefulWidget {
  const AuctionRoomScreen({
    super.key,
    required this.auctionId,
  });

  final String auctionId;

  @override
  ConsumerState<AuctionRoomScreen> createState() => _AuctionRoomScreenState();
}

class _AuctionRoomScreenState extends ConsumerState<AuctionRoomScreen>
    with TickerProviderStateMixin {
  bool _bidLoading = false;

  // ── Outbid banner ──────────────────────────────────────────────
  late AnimationController _outbidBannerController;
  late Animation<Offset> _outbidBannerSlide;
  BidButtonState _lastButtonState = BidButtonState.idle;

  // ── Entrance animations ────────────────────────────────────────
  late AnimationController _entranceCtrl;
  late Animation<double> _headerFade;
  late Animation<double> _priceFade;
  late Animation<double> _statsFade;

  @override
  void initState() {
    super.initState();
    _outbidBannerController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
      reverseDuration: const Duration(milliseconds: 300),
    );
    _outbidBannerSlide = Tween<Offset>(
      begin: const Offset(0, 1),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _outbidBannerController,
      curve: Curves.easeOutCubic,
      reverseCurve: Curves.easeIn,
    ));

    // Staggered entrance
    _entranceCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _headerFade = CurvedAnimation(
      parent: _entranceCtrl,
      curve: const Interval(0.0, 0.4, curve: Curves.easeOut),
    );
    _priceFade = CurvedAnimation(
      parent: _entranceCtrl,
      curve: const Interval(0.2, 0.6, curve: Curves.easeOut),
    );
    _statsFade = CurvedAnimation(
      parent: _entranceCtrl,
      curve: const Interval(0.4, 0.8, curve: Curves.easeOut),
    );
    _entranceCtrl.forward();
  }

  @override
  void dispose() {
    _outbidBannerController.dispose();
    _entranceCtrl.dispose();
    super.dispose();
  }

  void _checkOutbidState(BidButtonState buttonState) {
    if (buttonState == BidButtonState.outbid &&
        _lastButtonState != BidButtonState.outbid) {
      _outbidBannerController.forward();
      Future.delayed(const Duration(seconds: 5), () {
        if (mounted) _outbidBannerController.reverse();
      });
    }
    _lastButtonState = buttonState;
  }

  @override
  Widget build(BuildContext context) {
    final auction = ref.watch(auctionProvider(widget.auctionId));
    final auth = ref.watch(authProvider);
    final myId = auth.userId;
    final buttonState = _resolveBidButtonState(auction, myId);

    _checkOutbidState(buttonState);

    return Scaffold(
      backgroundColor: AppColors.cream,
      body: Stack(
        children: [
          // ── Main content ─────────────────────────────────────────
          SafeArea(
            child: Column(
              children: [
                // ── AppBar ────────────────────────────────────────
                _buildAppBar(context, auction),

                // ── Scrollable body ──────────────────────────────
                Expanded(
                  child: CustomScrollView(
                    slivers: [
                      SliverToBoxAdapter(
                        child: _buildTopSection(auction),
                      ),
                      // ── Bid history section ────────────────────
                      SliverToBoxAdapter(
                        child: Padding(
                          padding: const EdgeInsetsDirectional.only(
                            start: AppSpacing.md,
                            end: AppSpacing.md,
                            top: AppSpacing.sm,
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.history_rounded,
                                  size: 16, color: AppColors.mist),
                              const SizedBox(width: AppSpacing.xxs),
                              Text(
                                S.of(context).bidHistory,
                                style: const TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: AppColors.navy,
                                ),
                              ),
                              const Spacer(),
                              Text(
                                '${auction.bids.length}',
                                style: const TextStyle(
                                  fontSize: 13,
                                  color: AppColors.mist,
                                  fontFamily: 'Sora',
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      // ── Bid history feed or empty state ────────
                      if (auction.bids.isEmpty)
                        SliverFillRemaining(
                          hasScrollBody: false,
                          child: _EmptyBidHistory(
                            isEnded: auction.status == 'ended',
                          ),
                        )
                      else
                        SliverFillRemaining(
                          child: BidHistoryFeed(
                            bids: auction.bids,
                            currency: auction.currency,
                            animateInitialItems: true,
                          ),
                        ),
                    ],
                  ),
                ),

                // ── Bottom bid area ──────────────────────────────
                _buildBottomBidArea(context, auction, buttonState),
              ],
            ),
          ),

          // ── Connection status overlay ────────────────────────────
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: ConnectionStatusBanner(
              status: auction.connectionStatus,
            ),
          ),

          // ── Outbid banner (slides from bottom) ─────────────────
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            child: SlideTransition(
              position: _outbidBannerSlide,
              child: _OutbidBanner(),
            ),
          ),
        ],
      ),
    );
  }

  // ── Top section: listing info + timer + price + stats ──────────────

  Widget _buildTopSection(AuctionState auction) {
    return Container(
      margin: AppSpacing.horizontalMd,
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: AppSpacing.radiusLg,
        boxShadow: [
          BoxShadow(
            color: AppColors.navy.withValues(alpha: 0.06),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        children: [
          // ── Listing info (thumbnail + title) ─────────────────
          if (auction.imageUrl != null || auction.listingTitle != null)
            FadeTransition(
              opacity: _headerFade,
              child: _ListingInfoHeader(auction: auction),
            ),

          const SizedBox(height: AppSpacing.md),

          // ── Timer ──────────────────────────────────────────
          AuctionTimer(
            endsAt: auction.endsAt,
            timerRemaining: auction.timerRemaining,
            timerExtended: auction.timerExtended,
          ),

          const SizedBox(height: AppSpacing.lg),

          // ── Live price ──────────────────────────────────────
          FadeTransition(
            opacity: _priceFade,
            child: LivePriceDisplay(
              price: auction.currentPrice,
              currency: auction.currency,
              heroTag: HeroTags.price(widget.auctionId),
              animateEntry: true,
            ),
          ),

          const SizedBox(height: AppSpacing.sm),

          // ── Stats row ──────────────────────────────────────
          FadeTransition(
            opacity: _statsFade,
            child: _StatsRow(auction: auction),
          ),

          // ── Quick bid chips ────────────────────────────────
          if (auction.status != 'ended' && auction.isConnected)
            Padding(
              padding: const EdgeInsetsDirectional.only(top: AppSpacing.md),
              child: _QuickBidChips(
                minIncrement: auction.minIncrement,
                currency: auction.currency,
                onQuickBid: (amount) =>
                    _placeBid(auction.currentPrice + amount),
              ),
            ),
        ],
      ),
    );
  }

  // ── App bar ───────────────────────────────────────────────────────

  Widget _buildAppBar(BuildContext context, AuctionState auction) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.xs,
        vertical: AppSpacing.xs,
      ),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
            onPressed: () => Navigator.of(context).maybePop(),
            color: AppColors.navy,
          ),
          Expanded(
            child: Text(
              auction.listingTitle ?? 'المزاد',
              textAlign: TextAlign.center,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppColors.navy,
              ),
            ),
          ),
          // Watcher count + connection dot
          Container(
            padding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm, vertical: AppSpacing.xxs),
            decoration: BoxDecoration(
              color: auction.isConnected
                  ? AppColors.emerald.withValues(alpha: 0.1)
                  : AppColors.ember.withValues(alpha: 0.1),
              borderRadius: AppSpacing.radiusFull,
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: auction.isConnected
                        ? AppColors.emerald
                        : AppColors.ember,
                  ),
                ),
                if (auction.watcherCount > 0) ...[
                  const SizedBox(width: 4),
                  Text(
                    '${auction.watcherCount}',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      fontFamily: 'Sora',
                      color: auction.isConnected
                          ? AppColors.emerald
                          : AppColors.ember,
                    ),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
        ],
      ),
    );
  }

  // ── Bottom bid area ───────────────────────────────────────────────

  Widget _buildBottomBidArea(
    BuildContext context,
    AuctionState auction,
    BidButtonState buttonState,
  ) {
    return Container(
      padding: EdgeInsetsDirectional.only(
        start: AppSpacing.md,
        end: AppSpacing.md,
        top: AppSpacing.sm,
        bottom: MediaQuery.of(context).viewPadding.bottom + AppSpacing.sm,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        boxShadow: [
          BoxShadow(
            color: AppColors.navy.withValues(alpha: 0.06),
            blurRadius: 8,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Seller guard explanation
          if (auction.isSeller(ref.read(authProvider).userId))
            const Padding(
              padding: EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
              child: Text(
                'لا يمكنك المزايدة على قائمتك الخاصة',
                style: TextStyle(fontSize: 12, color: AppColors.ember),
              ),
            )
          // Next bid amount hint
          else if (buttonState != BidButtonState.disabled)
            Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.arrow_upward_rounded,
                      size: 14, color: AppColors.gold),
                  const SizedBox(width: 4),
                  Text(
                    'الحد الأدنى التالي: ${ArabicNumerals.formatCurrencyEn(
                      auction.currentPrice + auction.minIncrement,
                      auction.currency,
                    )}',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.mist,
                      fontFamily: 'Sora',
                    ),
                  ),
                ],
              ),
            ),

          // Error message
          if (auction.error != null)
            Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
              child: Container(
                padding: const EdgeInsetsDirectional.symmetric(
                    horizontal: AppSpacing.sm, vertical: AppSpacing.xxs),
                decoration: BoxDecoration(
                  color: AppColors.ember.withValues(alpha: 0.08),
                  borderRadius: AppSpacing.radiusSm,
                ),
                child: Text(
                  auction.error!,
                  style: const TextStyle(fontSize: 12, color: AppColors.ember),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),

          // Bid button
          BidButton(
            state: buttonState,
            onPressed: () => _onBidPressed(context, auction),
          ),
        ],
      ),
    );
  }

  BidButtonState _resolveBidButtonState(AuctionState auction, String? myId) {
    if (auction.status == 'ended') return BidButtonState.disabled;
    if (!auction.isConnected) return BidButtonState.disabled;
    if (auction.isSeller(myId)) return BidButtonState.disabled;
    if (_bidLoading) return BidButtonState.loading;
    if (myId != null && auction.lastBidder == myId) {
      return BidButtonState.leading;
    }
    if (auction.bids.isNotEmpty &&
        auction.bids.first.isOwn == false &&
        auction.lastBidder != null &&
        auction.lastBidder != myId &&
        auction.bids.any((b) => b.isOwn)) {
      return BidButtonState.outbid;
    }
    return BidButtonState.idle;
  }

  void _onBidPressed(BuildContext context, AuctionState auction) {
    AppHaptics.bidTap();

    BidInputSheet.show(
      context: context,
      currentPrice: auction.currentPrice,
      minIncrement: auction.minIncrement,
      currency: auction.currency,
      onConfirm: (amount, {bool isProxy = false}) {
        _placeBid(amount);
      },
    );
  }

  Future<void> _placeBid(double amount) async {
    setState(() => _bidLoading = true);

    final notifier = ref.read(auctionProvider(widget.auctionId).notifier);
    await notifier.placeBid(amount);

    if (mounted) {
      setState(() => _bidLoading = false);
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Listing info header — thumbnail + title
// ═══════════════════════════════════════════════════════════════════════

class _ListingInfoHeader extends StatelessWidget {
  const _ListingInfoHeader({required this.auction});
  final AuctionState auction;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: AppSpacing.allSm,
      decoration: BoxDecoration(
        color: AppColors.cream,
        borderRadius: AppSpacing.radiusMd,
      ),
      child: Row(
        children: [
          // Thumbnail
          if (auction.imageUrl != null)
            ClipRRect(
              borderRadius: AppSpacing.radiusSm,
              child: CachedNetworkImage(
                imageUrl: auction.imageUrl!,
                width: 52,
                height: 52,
                fit: BoxFit.cover,
                placeholder: (_, __) =>
                    Container(width: 52, height: 52, color: AppColors.sand),
                errorWidget: (_, __, ___) => Container(
                  width: 52,
                  height: 52,
                  color: AppColors.sand,
                  child: const Icon(Icons.image_rounded,
                      color: AppColors.mist, size: 24),
                ),
              ),
            ),
          if (auction.imageUrl != null)
            const SizedBox(width: AppSpacing.sm),
          // Title
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  auction.listingTitle ?? 'المزاد',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.ink,
                    height: 1.3,
                  ),
                ),
                const SizedBox(height: 2),
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsetsDirectional.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: auction.status == 'ended'
                            ? AppColors.mist.withValues(alpha: 0.15)
                            : AppColors.emerald.withValues(alpha: 0.12),
                        borderRadius: AppSpacing.radiusSm,
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (auction.status != 'ended')
                            Container(
                              width: 5,
                              height: 5,
                              margin:
                                  const EdgeInsetsDirectional.only(end: 4),
                              decoration: const BoxDecoration(
                                color: AppColors.emerald,
                                shape: BoxShape.circle,
                              ),
                            ),
                          Text(
                            auction.status == 'ended' ? 'انتهى' : 'مباشر',
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                              color: auction.status == 'ended'
                                  ? AppColors.mist
                                  : AppColors.emerald,
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (auction.extensionCount > 0) ...[
                      const SizedBox(width: AppSpacing.xs),
                      Text(
                        '${auction.extensionCount} تمديد',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.gold,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Stats row — bid count, watchers, extensions
// ═══════════════════════════════════════════════════════════════════════

class _StatsRow extends StatelessWidget {
  const _StatsRow({required this.auction});
  final AuctionState auction;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _StatChip(
          icon: Icons.gavel_rounded,
          value: auction.bidCount,
          label: S.of(context).bidTab,
          color: AppColors.navy,
        ),
        const SizedBox(width: AppSpacing.md),
        _StatChip(
          icon: Icons.visibility_rounded,
          value: auction.watcherCount,
          label: S.of(context).viewersTab,
          color: AppColors.emerald,
        ),
        if (auction.extensionCount > 0) ...[
          const SizedBox(width: AppSpacing.md),
          _StatChip(
            icon: Icons.update_rounded,
            value: auction.extensionCount,
            label: S.of(context).extensionTab,
            color: AppColors.gold,
          ),
        ],
      ],
    );
  }
}

class _StatChip extends StatelessWidget {
  const _StatChip({
    required this.icon,
    required this.value,
    required this.label,
    required this.color,
  });
  final IconData icon;
  final int value;
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
          horizontal: AppSpacing.sm, vertical: AppSpacing.xxs),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: AppSpacing.radiusFull,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 4),
          CountUpInt(
            value: value,
            duration: const Duration(milliseconds: 600),
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: color,
              fontFamily: 'Sora',
            ),
          ),
          const SizedBox(width: 3),
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Quick bid chips — preset increment buttons
// ═══════════════════════════════════════════════════════════════════════

class _QuickBidChips extends StatelessWidget {
  const _QuickBidChips({
    required this.minIncrement,
    required this.currency,
    required this.onQuickBid,
  });

  final double minIncrement;
  final String currency;
  final ValueChanged<double> onQuickBid;

  @override
  Widget build(BuildContext context) {
    final increments = [
      minIncrement,
      minIncrement * 2,
      minIncrement * 5,
      minIncrement * 10,
    ];

    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: increments.map((inc) {
        return Padding(
          padding: const EdgeInsetsDirectional.symmetric(horizontal: 4),
          child: GestureDetector(
            onTap: () {
              AppHaptics.bidTap();
              onQuickBid(inc);
            },
            child: Container(
              padding: const EdgeInsetsDirectional.symmetric(
                  horizontal: AppSpacing.sm, vertical: AppSpacing.xxs),
              decoration: BoxDecoration(
                color: AppColors.gold.withValues(alpha: 0.1),
                borderRadius: AppSpacing.radiusFull,
                border: Border.all(
                    color: AppColors.gold.withValues(alpha: 0.25)),
              ),
              child: Text(
                '+${ArabicNumerals.formatCurrencyEn(inc, currency)}',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.gold,
                  fontFamily: 'Sora',
                ),
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Empty bid history state
// ═══════════════════════════════════════════════════════════════════════

class _EmptyBidHistory extends StatelessWidget {
  const _EmptyBidHistory({this.isEnded = false});
  final bool isEnded;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: AppSpacing.allXl,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              isEnded
                  ? Icons.gavel_rounded
                  : Icons.front_hand_rounded,
              size: 48,
              color: AppColors.sand,
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              isEnded ? 'لم تُقدَّم أي مزايدات' : 'كن أول من يزايد!',
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppColors.mist,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              isEnded
                  ? 'انتهى المزاد دون أي مزايدات'
                  : 'ابدأ المزايدة الآن واحصل على فرصتك',
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 13,
                color: AppColors.mist,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Outbid banner — slides in from bottom, auto-dismissed after 5s
// ═══════════════════════════════════════════════════════════════════════

class _OutbidBanner extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsetsDirectional.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        margin: EdgeInsetsDirectional.only(
          start: AppSpacing.md,
          end: AppSpacing.md,
          bottom: MediaQuery.of(context).viewPadding.bottom + 80,
        ),
        decoration: BoxDecoration(
          color: AppColors.ember,
          borderRadius: AppSpacing.radiusMd,
          boxShadow: [
            BoxShadow(
              color: AppColors.ember.withValues(alpha: 0.3),
              blurRadius: 12,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.warning_amber_rounded, color: Colors.white, size: 20),
            SizedBox(width: AppSpacing.xs),
            Text(
              'تم تجاوز مزايدتك!',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
