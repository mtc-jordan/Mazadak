import 'package:flutter/material.dart';

import '../../../core/l10n/arabic_numerals.dart';
import '../../../core/providers/auction_provider.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Flash color for new bid row.
const _newBidFlash = Color(0xFFD6E4FF); // blue flash
const _ownBidColor = Color(0xFFD5F5E3);  // green highlight
const _pendingBidColor = Color(0xFFFFF3CD); // amber pending

/// Stagger delay between each row on initial entry.
const _staggerDelay = Duration(milliseconds: 30);

/// Bid history feed with animated insertions.
///
/// SDD §7.2:
/// - AnimatedList, insertItem(0) for new bids
/// - Each row: SlideTransition(Offset(0,-1)→Offset.zero) + FadeTransition, 180ms
/// - New bid row: blue flash background fades in 800ms
/// - Max 50 items, masked bidder names, own bids highlighted green
/// - On auction room entry: staggers in from bottom, 30ms per row
class BidHistoryFeed extends StatefulWidget {
  const BidHistoryFeed({
    super.key,
    required this.bids,
    required this.currency,
    this.locale = 'ar_JO',
    this.animateInitialItems = true,
  });

  final List<BidEntry> bids;
  final String currency;
  final String locale;

  /// When true, initial items stagger in from bottom on first build.
  final bool animateInitialItems;

  @override
  State<BidHistoryFeed> createState() => _BidHistoryFeedState();
}

class _BidHistoryFeedState extends State<BidHistoryFeed>
    with TickerProviderStateMixin {
  final _listKey = GlobalKey<AnimatedListState>();
  List<BidEntry> _displayedBids = [];
  bool _initialAnimationDone = false;

  // Stagger controllers for initial entry
  final List<AnimationController> _staggerControllers = [];
  final List<Animation<double>> _staggerAnimations = [];

  @override
  void initState() {
    super.initState();
    if (widget.animateInitialItems && widget.bids.isNotEmpty) {
      // Start with empty list, then stagger items in
      _displayedBids = [];
      _scheduleStaggeredEntry();
    } else {
      _displayedBids = List.of(widget.bids);
      _initialAnimationDone = true;
    }
  }

  void _scheduleStaggeredEntry() {
    final bids = widget.bids;
    // Create stagger animation controllers for each initial bid
    for (var i = 0; i < bids.length; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 250),
      );
      final animation = CurvedAnimation(
        parent: controller,
        curve: Curves.easeOutCubic,
      );
      _staggerControllers.add(controller);
      _staggerAnimations.add(animation);
    }

    // Stagger the insertions: 30ms delay per row
    Future<void> staggerInserts() async {
      for (var i = 0; i < bids.length; i++) {
        if (!mounted) return;
        _displayedBids.add(bids[i]);
        _listKey.currentState?.insertItem(
          _displayedBids.length - 1,
          duration: const Duration(milliseconds: 250),
        );
        if (i < bids.length - 1) {
          await Future.delayed(_staggerDelay);
        }
      }
      if (mounted) {
        setState(() => _initialAnimationDone = true);
      }
    }

    // Kick off after first frame
    WidgetsBinding.instance.addPostFrameCallback((_) {
      staggerInserts();
    });
  }

  @override
  void didUpdateWidget(BidHistoryFeed old) {
    super.didUpdateWidget(old);
    if (!_initialAnimationDone) return;

    final newBids = widget.bids;
    final oldBids = _displayedBids;

    // Detect new bids inserted at the front
    if (newBids.length > oldBids.length) {
      final insertCount = newBids.length - oldBids.length;
      for (var i = 0; i < insertCount; i++) {
        _listKey.currentState?.insertItem(0, duration: const Duration(milliseconds: 180));
      }
    }

    // Detect bids removed (rollback)
    if (newBids.length < oldBids.length) {
      final removeCount = oldBids.length - newBids.length;
      for (var i = 0; i < removeCount; i++) {
        final removed = oldBids[i];
        _listKey.currentState?.removeItem(
          0,
          (context, animation) => _buildItem(removed, animation),
          duration: const Duration(milliseconds: 180),
        );
      }
    }

    _displayedBids = List.of(newBids);
  }

  @override
  void dispose() {
    for (final c in _staggerControllers) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedList(
      key: _listKey,
      initialItemCount: _displayedBids.length,
      padding: AppSpacing.verticalXs,
      itemBuilder: (context, index, animation) {
        if (index >= _displayedBids.length) return const SizedBox.shrink();

        // During staggered initial entry, rows slide in from bottom
        if (!_initialAnimationDone) {
          return _buildStaggerItem(_displayedBids[index], animation);
        }

        return _buildItem(_displayedBids[index], animation);
      },
    );
  }

  /// Staggered entry: slide from bottom + fade (initial load).
  Widget _buildStaggerItem(BidEntry bid, Animation<double> animation) {
    return SlideTransition(
      position: Tween<Offset>(
        begin: const Offset(0, 0.3),
        end: Offset.zero,
      ).animate(CurvedAnimation(
        parent: animation,
        curve: Curves.easeOutCubic,
      )),
      child: FadeTransition(
        opacity: animation,
        child: _BidRow(
          bid: bid,
          currency: widget.currency,
          locale: widget.locale,
          suppressFlash: true, // no flash on initial load
        ),
      ),
    );
  }

  /// Standard new-bid entry: slide from top + fade.
  Widget _buildItem(BidEntry bid, Animation<double> animation) {
    return SlideTransition(
      position: Tween<Offset>(
        begin: const Offset(0, -1),
        end: Offset.zero,
      ).animate(CurvedAnimation(
        parent: animation,
        curve: Curves.easeOutCubic,
      )),
      child: FadeTransition(
        opacity: animation,
        child: _BidRow(
          bid: bid,
          currency: widget.currency,
          locale: widget.locale,
        ),
      ),
    );
  }
}

/// Individual bid row with flash animation.
class _BidRow extends StatefulWidget {
  const _BidRow({
    required this.bid,
    required this.currency,
    required this.locale,
    this.suppressFlash = false,
  });

  final BidEntry bid;
  final String currency;
  final String locale;
  final bool suppressFlash;

  @override
  State<_BidRow> createState() => _BidRowState();
}

class _BidRowState extends State<_BidRow> with SingleTickerProviderStateMixin {
  late AnimationController _flashController;
  late Animation<Color?> _flashAnimation;

  @override
  void initState() {
    super.initState();
    _flashController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );

    final baseColor = widget.bid.isOwn
        ? _ownBidColor
        : widget.bid.isPending
            ? _pendingBidColor
            : _newBidFlash;

    _flashAnimation = ColorTween(
      begin: widget.suppressFlash ? Colors.transparent : baseColor,
      end: widget.bid.isOwn ? _ownBidColor.withValues(alpha: 0.3) : Colors.transparent,
    ).animate(CurvedAnimation(
      parent: _flashController,
      curve: Curves.easeOut,
    ));

    // Trigger flash on mount (new bid) — skip for initial stagger
    if (!widget.suppressFlash) {
      _flashController.forward();
    } else {
      _flashController.value = 1.0; // jump to end
    }
  }

  @override
  void dispose() {
    _flashController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final amount = ArabicNumerals.formatCurrency(
      widget.bid.amount,
      widget.currency,
      locale: widget.locale,
    );

    return AnimatedBuilder(
      animation: _flashAnimation,
      builder: (context, child) {
        return Container(
          decoration: BoxDecoration(
            color: _flashAnimation.value,
            border: widget.bid.isOwn
                ? const Border(
                    left: BorderSide(color: AppColors.emerald, width: 2),
                  )
                : null,
          ),
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
          child: child,
        );
      },
      child: Row(
        children: [
          // Bidder avatar / icon
          Container(
            width: 32,
            height: 32,
            decoration: BoxDecoration(
              color: widget.bid.isOwn
                  ? AppColors.emerald.withValues(alpha: 0.15)
                  : AppColors.navy.withValues(alpha: 0.08),
              shape: BoxShape.circle,
            ),
            child: Icon(
              widget.bid.isOwn ? Icons.person : Icons.person_outline,
              size: 16,
              color: widget.bid.isOwn ? AppColors.emerald : AppColors.mist,
            ),
          ),
          const SizedBox(width: AppSpacing.sm),

          // Name + time
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.bid.isOwn ? 'أنت' : _maskName(widget.bid.userId),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight:
                        widget.bid.isOwn ? FontWeight.w600 : FontWeight.w400,
                    color: widget.bid.isOwn ? AppColors.emerald : AppColors.ink,
                  ),
                ),
                if (widget.bid.isPending)
                  Text(
                    'قيد التأكيد...',
                    style: TextStyle(
                      fontSize: 11,
                      color: AppColors.gold,
                      fontStyle: FontStyle.italic,
                    ),
                  ),
              ],
            ),
          ),

          // Amount
          Text(
            amount,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: widget.bid.isOwn ? AppColors.emerald : AppColors.navy,
            ),
          ),
        ],
      ),
    );
  }

  /// Mask bidder name for privacy: "abc-12345-..." → "مزايد ***45"
  String _maskName(String userId) {
    if (userId.length < 4) return 'مزايد ***';
    final suffix = userId.substring(userId.length - 2);
    return 'مزايد ***$suffix';
  }
}
