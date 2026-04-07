import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/auction_provider.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/haptics.dart';
import '../../core/theme/spacing.dart';
import 'widgets/auction_timer.dart';
import 'widgets/bid_button.dart';
import 'widgets/bid_history_feed.dart';
import 'widgets/bid_input_sheet.dart';
import 'widgets/connection_status_banner.dart';
import 'widgets/live_price_display.dart';

/// AuctionRoomScreen — the most important screen in the app.
///
/// SDD §7.2: Composes all 7 auction components:
/// 1. ConnectionStatusBanner (top, overlay)
/// 2. AuctionTimer (countdown with urgency cues)
/// 3. LivePriceDisplay (per-digit animation, amber flash)
/// 4. BidHistoryFeed (animated list with slide-in)
/// 5. BidButton (5 states with spring transitions)
/// 6. BidInputSheet (modal stepper)
///
/// Wired to auctionProvider(id) for real-time WebSocket state.
/// Optimistic bid: shows pending immediately, rolls back after 3s if no server confirm.
class AuctionRoomScreen extends ConsumerStatefulWidget {
  const AuctionRoomScreen({
    super.key,
    required this.auctionId,
  });

  final String auctionId;

  @override
  ConsumerState<AuctionRoomScreen> createState() => _AuctionRoomScreenState();
}

class _AuctionRoomScreenState extends ConsumerState<AuctionRoomScreen> {
  bool _bidLoading = false;

  @override
  Widget build(BuildContext context) {
    final auction = ref.watch(auctionProvider(widget.auctionId));
    final auth = ref.watch(authProvider);
    final myId = auth.userId;

    // Determine bid button state
    final buttonState = _resolveBidButtonState(auction, myId);

    return Scaffold(
      body: Stack(
        children: [
          // ── Main content ─────────────────────────────────────────
          SafeArea(
            child: Column(
              children: [
                // ── AppBar area ────────────────────────────────────
                _buildAppBar(context, auction),

                // ── Timer + Price section ──────────────────────────
                Padding(
                  padding: AppSpacing.horizontalMd,
                  child: Column(
                    children: [
                      const SizedBox(height: AppSpacing.md),

                      // Timer
                      AuctionTimer(
                        endsAt: auction.endsAt,
                        timerExtended: auction.timerExtended,
                      ),

                      const SizedBox(height: AppSpacing.lg),

                      // Live price
                      LivePriceDisplay(
                        price: auction.currentPrice,
                        currency: auction.currency,
                      ),

                      const SizedBox(height: AppSpacing.xs),

                      // Bid count
                      Text(
                        '${ArabicNumerals.formatNumber(auction.bidCount)} مزايدة',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.mist,
                        ),
                      ),

                      const SizedBox(height: AppSpacing.sm),
                      const Divider(),
                    ],
                  ),
                ),

                // ── Bid history feed (scrollable) ──────────────────
                Expanded(
                  child: BidHistoryFeed(
                    bids: auction.bids,
                    currency: auction.currency,
                  ),
                ),

                // ── Bottom bid area ────────────────────────────────
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
        ],
      ),
    );
  }

  Widget _buildAppBar(BuildContext context, AuctionState auction) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
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
          // Connection indicator dot
          Container(
            width: 10,
            height: 10,
            margin: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: auction.isConnected
                  ? AppColors.emerald
                  : AppColors.ember,
            ),
          ),
        ],
      ),
    );
  }

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
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(
          top: BorderSide(color: AppColors.sand, width: 1),
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Next bid amount hint
          if (buttonState != BidButtonState.disabled)
            Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
              child: Text(
                'الحد الأدنى التالي: ${ArabicNumerals.formatCurrency(
                  auction.currentPrice + auction.minIncrement,
                  auction.currency,
                )}',
                style: const TextStyle(fontSize: 12, color: AppColors.mist),
              ),
            ),

          // Error message
          if (auction.error != null)
            Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
              child: Text(
                auction.error!,
                style: const TextStyle(
                  fontSize: 12,
                  color: AppColors.ember,
                ),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
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
    if (_bidLoading) return BidButtonState.loading;
    if (myId != null && auction.lastBidder == myId) return BidButtonState.leading;
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

    // Loading state resets when server confirms via WebSocket (bid_accepted)
    // or after optimistic rollback timeout (3s)
    if (mounted) {
      setState(() => _bidLoading = false);
    }
  }
}
