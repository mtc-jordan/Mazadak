import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/core_providers.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import '../../widgets/mzadak_refresh_indicator.dart';

// ══════════════════════════════════════════════════════════════════
// Models
// ══════════════════════════════════════════════════════════════════

enum BidStatus { leading, outbid, pending }

class UserBid {
  const UserBid({
    required this.id,
    required this.listingId,
    required this.auctionId,
    required this.titleEn,
    required this.titleAr,
    required this.imageUrl,
    required this.yourAmount,
    required this.currentPrice,
    required this.currency,
    required this.status,
    this.endsAt,
    this.bidCount = 0,
    this.category,
  });

  final String id;
  final String listingId;
  final String auctionId;
  final String titleEn;
  final String titleAr;
  final String imageUrl;
  final double yourAmount;
  final double currentPrice;
  final String currency;
  final BidStatus status;
  final String? endsAt;
  final int bidCount;
  final String? category;

  factory UserBid.fromJson(Map<String, dynamic> json) {
    final statusStr = json['status'] as String? ?? 'pending';
    final status = switch (statusStr) {
      'leading' => BidStatus.leading,
      'outbid' => BidStatus.outbid,
      _ => BidStatus.pending,
    };
    return UserBid(
      id: json['id'] as String,
      listingId: json['listing_id'] as String,
      auctionId: json['auction_id'] as String,
      titleEn: json['title_en'] as String? ?? json['title_ar'] as String,
      titleAr: json['title_ar'] as String,
      imageUrl: json['image_url'] as String? ?? '',
      yourAmount: (json['your_amount'] as num).toDouble(),
      currentPrice: (json['current_price'] as num).toDouble(),
      currency: json['currency'] as String? ?? 'JOD',
      status: status,
      endsAt: json['ends_at'] as String?,
      bidCount: json['bid_count'] as int? ?? 0,
      category: json['category'] as String?,
    );
  }
}

class WonBid {
  const WonBid({
    required this.id,
    required this.listingId,
    required this.escrowId,
    required this.titleEn,
    required this.titleAr,
    required this.imageUrl,
    required this.finalPrice,
    required this.currency,
    required this.escrowStatus,
    this.paymentDeadline,
  });

  final String id;
  final String listingId;
  final String escrowId;
  final String titleEn;
  final String titleAr;
  final String imageUrl;
  final double finalPrice;
  final String currency;
  final String escrowStatus; // awaiting_payment, shipping, in_transit, complete
  final String? paymentDeadline;

  factory WonBid.fromJson(Map<String, dynamic> json) => WonBid(
        id: json['id'] as String,
        listingId: json['listing_id'] as String,
        escrowId: json['escrow_id'] as String? ?? json['id'] as String,
        titleEn: json['title_en'] as String? ?? json['title_ar'] as String,
        titleAr: json['title_ar'] as String,
        imageUrl: json['image_url'] as String? ?? '',
        finalPrice: (json['final_price'] as num).toDouble(),
        currency: json['currency'] as String? ?? 'JOD',
        escrowStatus: json['escrow_status'] as String? ?? 'awaiting_payment',
        paymentDeadline: json['payment_deadline'] as String?,
      );
}

class LostBid {
  const LostBid({
    required this.id,
    required this.listingId,
    required this.titleEn,
    required this.titleAr,
    required this.imageUrl,
    required this.yourAmount,
    required this.finalPrice,
    required this.currency,
    required this.winnerMasked,
    this.category,
  });

  final String id;
  final String listingId;
  final String titleEn;
  final String titleAr;
  final String imageUrl;
  final double yourAmount;
  final double finalPrice;
  final String currency;
  final String winnerMasked;
  final String? category;

  factory LostBid.fromJson(Map<String, dynamic> json) => LostBid(
        id: json['id'] as String,
        listingId: json['listing_id'] as String,
        titleEn: json['title_en'] as String? ?? json['title_ar'] as String,
        titleAr: json['title_ar'] as String,
        imageUrl: json['image_url'] as String? ?? '',
        yourAmount: (json['your_amount'] as num).toDouble(),
        finalPrice: (json['final_price'] as num).toDouble(),
        currency: json['currency'] as String? ?? 'JOD',
        winnerMasked: json['winner_masked'] as String? ?? 'م***س',
        category: json['category'] as String?,
      );
}

class WatchlistItem {
  const WatchlistItem({
    required this.id,
    required this.listingId,
    required this.titleEn,
    required this.titleAr,
    required this.imageUrl,
    required this.currentPrice,
    required this.currency,
    this.endsAt,
    this.bidCount = 0,
  });

  final String id;
  final String listingId;
  final String titleEn;
  final String titleAr;
  final String imageUrl;
  final double currentPrice;
  final String currency;
  final String? endsAt;
  final int bidCount;

  factory WatchlistItem.fromJson(Map<String, dynamic> json) => WatchlistItem(
        id: json['id'] as String,
        listingId: json['listing_id'] as String? ?? json['id'] as String,
        titleEn: json['title_en'] as String? ?? json['title_ar'] as String,
        titleAr: json['title_ar'] as String,
        imageUrl: json['image_url'] as String? ?? '',
        currentPrice: (json['current_price'] as num?)?.toDouble() ?? 0,
        currency: json['currency'] as String? ?? 'JOD',
        endsAt: json['ends_at'] as String?,
        bidCount: json['bid_count'] as int? ?? 0,
      );
}

// ══════════════════════════════════════════════════════════════════
// Provider
// ══════════════════════════════════════════════════════════════════

class MyBidsState {
  const MyBidsState({
    this.active = const [],
    this.won = const [],
    this.lost = const [],
    this.watchlist = const [],
    this.isLoading = false,
    this.error,
  });

  final List<UserBid> active;
  final List<WonBid> won;
  final List<LostBid> lost;
  final List<WatchlistItem> watchlist;
  final bool isLoading;
  final String? error;

  MyBidsState copyWith({
    List<UserBid>? active,
    List<WonBid>? won,
    List<LostBid>? lost,
    List<WatchlistItem>? watchlist,
    bool? isLoading,
    String? error,
  }) =>
      MyBidsState(
        active: active ?? this.active,
        won: won ?? this.won,
        lost: lost ?? this.lost,
        watchlist: watchlist ?? this.watchlist,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

final myBidsProvider =
    StateNotifierProvider.autoDispose<MyBidsNotifier, MyBidsState>((ref) {
  return MyBidsNotifier(ref);
});

class MyBidsNotifier extends StateNotifier<MyBidsState> {
  MyBidsNotifier(this._ref) : super(const MyBidsState()) {
    load();
  }

  final Ref _ref;

  Future<void> load() async {
    if (state.isLoading) return;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/bids/mine');
      final data = resp.data as Map<String, dynamic>;

      state = MyBidsState(
        active: (data['active'] as List?)
                ?.map((e) => UserBid.fromJson(e as Map<String, dynamic>))
                .toList() ??
            const [],
        won: (data['won'] as List?)
                ?.map((e) => WonBid.fromJson(e as Map<String, dynamic>))
                .toList() ??
            const [],
        lost: (data['lost'] as List?)
                ?.map((e) => LostBid.fromJson(e as Map<String, dynamic>))
                .toList() ??
            const [],
        watchlist: (data['watchlist'] as List?)
                ?.map(
                    (e) => WatchlistItem.fromJson(e as Map<String, dynamic>))
                .toList() ??
            const [],
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> refresh() => load();

  Future<void> removeFromWatchlist(String listingId) async {
    // Optimistic removal
    final removed = state.watchlist.firstWhere(
      (w) => w.listingId == listingId,
      orElse: () => state.watchlist.first,
    );
    final updated =
        state.watchlist.where((w) => w.listingId != listingId).toList();
    state = state.copyWith(watchlist: updated);

    try {
      final api = _ref.read(apiClientProvider);
      await api.delete('/listings/$listingId/watch');
    } catch (_) {
      // Rollback on failure
      state = state.copyWith(watchlist: [...updated, removed]);
    }
  }

  void undoWatchlistRemoval(WatchlistItem item) {
    state = state.copyWith(watchlist: [...state.watchlist, item]);
    // Re-add on server
    final api = _ref.read(apiClientProvider);
    api.post('/listings/${item.listingId}/watch');
  }
}

// ══════════════════════════════════════════════════════════════════
// Screen
// ══════════════════════════════════════════════════════════════════

class MyBidsScreen extends ConsumerStatefulWidget {
  const MyBidsScreen({super.key});

  @override
  ConsumerState<MyBidsScreen> createState() => _MyBidsScreenState();
}

class _MyBidsScreenState extends ConsumerState<MyBidsScreen> {
  int _tabIndex = 0;

  static const _tabLabels = ['Active bids', 'Won', 'Lost', 'Watchlist'];

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(myBidsProvider);

    final counts = [
      state.active.length,
      state.won.length,
      state.lost.length,
      state.watchlist.length,
    ];

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        title: const Column(
          children: [
            Text(
              'My bids',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'مزايداتي',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: Column(
        children: [
          // Tab bar
          _TabBar(
            labels: _tabLabels,
            counts: counts,
            selectedIndex: _tabIndex,
            onTap: (i) => setState(() => _tabIndex = i),
          ),

          // Tab content
          Expanded(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 150),
              child: _buildTab(state),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTab(MyBidsState state) {
    if (state.isLoading &&
        state.active.isEmpty &&
        state.won.isEmpty &&
        state.lost.isEmpty &&
        state.watchlist.isEmpty) {
      return const Center(
        key: ValueKey('loading'),
        child: CircularProgressIndicator(color: AppColors.navy),
      );
    }

    return switch (_tabIndex) {
      0 => _ActiveBidsTab(
          key: const ValueKey('tab-active'),
          bids: state.active,
          onRefresh: () => ref.read(myBidsProvider.notifier).refresh(),
        ),
      1 => _WonTab(
          key: const ValueKey('tab-won'),
          bids: state.won,
          onRefresh: () => ref.read(myBidsProvider.notifier).refresh(),
        ),
      2 => _LostTab(
          key: const ValueKey('tab-lost'),
          bids: state.lost,
          onRefresh: () => ref.read(myBidsProvider.notifier).refresh(),
        ),
      3 => _WatchlistTab(
          key: const ValueKey('tab-watchlist'),
          items: state.watchlist,
          onRefresh: () => ref.read(myBidsProvider.notifier).refresh(),
          onRemove: (item) {
            ref
                .read(myBidsProvider.notifier)
                .removeFromWatchlist(item.listingId);
            _showUndoSnackbar(context, item);
          },
        ),
      _ => const SizedBox.shrink(),
    };
  }

  void _showUndoSnackbar(BuildContext context, WatchlistItem item) {
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(S.of(context).removedFromWatchlist),
        duration: const Duration(seconds: 3),
        action: SnackBarAction(
          label: S.of(context).undo,
          textColor: AppColors.gold,
          onPressed: () {
            ref.read(myBidsProvider.notifier).undoWatchlistRemoval(item);
          },
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Tab Bar (reusable pill-style, matches MyListingsScreen)
// ══════════════════════════════════════════════════════════════════

class _TabBar extends StatelessWidget {
  const _TabBar({
    required this.labels,
    required this.counts,
    required this.selectedIndex,
    required this.onTap,
  });

  final List<String> labels;
  final List<int> counts;
  final int selectedIndex;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AppColors.cream,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      child: Row(
        children: List.generate(labels.length, (i) {
          final isSelected = i == selectedIndex;
          return Expanded(
            child: GestureDetector(
              onTap: () => onTap(i),
              behavior: HitTestBehavior.opaque,
              child: Center(
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  curve: Curves.easeOutCubic,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                  decoration: BoxDecoration(
                    color: isSelected ? AppColors.navy : Colors.transparent,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Flexible(
                        child: Text(
                          labels[i],
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color:
                                isSelected ? Colors.white : AppColors.mist,
                          ),
                        ),
                      ),
                      if (counts[i] > 0) ...[
                        const SizedBox(width: 4),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 5,
                            vertical: 1,
                          ),
                          decoration: BoxDecoration(
                            color: isSelected
                                ? Colors.white.withOpacity(0.2)
                                : AppColors.sand,
                            borderRadius: BorderRadius.circular(10),
                          ),
                          child: Text(
                            '${counts[i]}',
                            style: TextStyle(
                              fontFamily: 'Sora',
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                              color: isSelected
                                  ? Colors.white
                                  : AppColors.navy,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Active Bids Tab
// ══════════════════════════════════════════════════════════════════

class _ActiveBidsTab extends StatelessWidget {
  const _ActiveBidsTab({
    super.key,
    required this.bids,
    required this.onRefresh,
  });

  final List<UserBid> bids;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (bids.isEmpty) {
      return _EmptyState(
        icon: Icons.gavel_rounded,
        title: S.of(context).noActiveBids,
        titleAr: 'لا توجد مزايدات نشطة',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(
          top: AppSpacing.xs,
          bottom: AppSpacing.xxxl,
        ),
        itemCount: bids.length,
        itemBuilder: (_, i) => _ActiveBidCard(bid: bids[i]),
      ),
    );
  }
}

class _ActiveBidCard extends StatefulWidget {
  const _ActiveBidCard({required this.bid});
  final UserBid bid;

  @override
  State<_ActiveBidCard> createState() => _ActiveBidCardState();
}

class _ActiveBidCardState extends State<_ActiveBidCard>
    with SingleTickerProviderStateMixin {
  late final AnimationController _shakeController;
  late final Animation<double> _shakeOffset;

  @override
  void initState() {
    super.initState();
    _shakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 250),
    );

    // ±3px, 2 cycles
    _shakeOffset = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: 3), weight: 1),
      TweenSequenceItem(tween: Tween(begin: 3, end: -3), weight: 1),
      TweenSequenceItem(tween: Tween(begin: -3, end: 3), weight: 1),
      TweenSequenceItem(tween: Tween(begin: 3, end: -3), weight: 1),
      TweenSequenceItem(tween: Tween(begin: -3, end: 0), weight: 1),
    ]).animate(CurvedAnimation(
      parent: _shakeController,
      curve: Curves.easeInOut,
    ));

    // Shake once on appearance if outbid
    if (widget.bid.status == BidStatus.outbid) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _shakeController.forward(from: 0);
          HapticFeedback.heavyImpact();
        }
      });
    }
  }

  @override
  void dispose() {
    _shakeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bid = widget.bid;
    final isOutbid = bid.status == BidStatus.outbid;

    return AnimatedBuilder(
      animation: _shakeOffset,
      builder: (_, child) => Transform.translate(
        offset: Offset(_shakeOffset.value, 0),
        child: child,
      ),
      child: Container(
        margin: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.xxs + 2,
        ),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: isOutbid
              ? const BorderDirectional(
                  start: BorderSide(color: AppColors.ember, width: 2),
                )
              : null,
        ),
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(12),
          child: InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: () => context.push('/auction/${bid.auctionId}'),
            child: Padding(
              padding: AppSpacing.allMd,
              child: Row(
                children: [
                  // Image
                  ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: CachedNetworkImage(
                      imageUrl: bid.imageUrl,
                      width: 60,
                      height: 60,
                      fit: BoxFit.cover,
                      placeholder: (_, __) => Container(
                        width: 60,
                        height: 60,
                        color: AppColors.sand,
                      ),
                      errorWidget: (_, __, ___) => Container(
                        width: 60,
                        height: 60,
                        color: AppColors.sand,
                        child: const Icon(Icons.image,
                            color: AppColors.mist, size: 20),
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.sm),

                  // Info
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          bid.titleEn,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.ink,
                          ),
                        ),
                        const SizedBox(height: 3),
                        Text(
                          'Your bid: ${ArabicNumerals.formatCurrencyEn(bid.yourAmount, bid.currency)}',
                          style: const TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.navy,
                          ),
                        ),
                        const SizedBox(height: 5),
                        // Status chip
                        _BidStatusChip(bid: bid),
                        // Timer
                        if (bid.endsAt != null) ...[
                          const SizedBox(height: 4),
                          _CountdownTimer(endsAt: bid.endsAt!),
                        ],
                      ],
                    ),
                  ),

                  // Chevron
                  const Icon(
                    Icons.chevron_right_rounded,
                    color: AppColors.mist,
                    size: 20,
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

class _BidStatusChip extends StatefulWidget {
  const _BidStatusChip({required this.bid});
  final UserBid bid;

  @override
  State<_BidStatusChip> createState() => _BidStatusChipState();
}

class _BidStatusChipState extends State<_BidStatusChip>
    with SingleTickerProviderStateMixin {
  AnimationController? _pulseController;

  @override
  void initState() {
    super.initState();
    if (widget.bid.status == BidStatus.leading) {
      _pulseController = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 1200),
      )..repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _pulseController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bid = widget.bid;

    final (Color bg, Color fg, String label) = switch (bid.status) {
      BidStatus.leading => (
          AppColors.emerald.withOpacity(0.12),
          AppColors.emerald,
          'Leading · أنت في المقدمة',
        ),
      BidStatus.outbid => (
          AppColors.ember.withOpacity(0.12),
          AppColors.ember,
          'Outbid! ${ArabicNumerals.formatCurrencyEn(bid.currentPrice, bid.currency)} now',
        ),
      BidStatus.pending => (
          AppColors.mist.withOpacity(0.12),
          AppColors.mist,
          'Bid placed · تم المزايدة',
        ),
    };

    Widget chip = Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontFamily: 'Sora',
          fontSize: 10,
          fontWeight: FontWeight.w700,
          color: fg,
        ),
      ),
    );

    // Pulse for leading — scale 1.0 → 1.04 loop
    if (_pulseController != null) {
      chip = AnimatedBuilder(
        animation: _pulseController!,
        builder: (_, child) {
          final scale = 1.0 + 0.04 * _pulseController!.value;
          return Transform.scale(scale: scale, child: child);
        },
        child: chip,
      );
    }

    // Outbid: show "Bid again" button
    if (bid.status == BidStatus.outbid) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          chip,
          const SizedBox(height: 4),
          GestureDetector(
            onTap: () => context.push('/auction/${bid.auctionId}'),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.ember,
                borderRadius: BorderRadius.circular(10),
              ),
              child: const Text(
                'Bid again →',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                ),
              ),
            ),
          ),
        ],
      );
    }

    return chip;
  }
}

class _CountdownTimer extends StatefulWidget {
  const _CountdownTimer({required this.endsAt});
  final String endsAt;

  @override
  State<_CountdownTimer> createState() => _CountdownTimerState();
}

class _CountdownTimerState extends State<_CountdownTimer> {
  late DateTime _endsAt;
  Timer? _timer;
  Duration _remaining = Duration.zero;

  @override
  void initState() {
    super.initState();
    _endsAt = DateTime.tryParse(widget.endsAt) ?? DateTime.now();
    _tick();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  void _tick() {
    if (!mounted) return;
    final diff = _endsAt.difference(DateTime.now());
    setState(() => _remaining = diff.isNegative ? Duration.zero : diff);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String get _formatted {
    if (_remaining == Duration.zero) return 'Ended';
    final h = _remaining.inHours;
    final m = _remaining.inMinutes % 60;
    final s = _remaining.inSeconds % 60;
    if (h > 0) return '${h}h ${m}m';
    if (m > 0) return '${m}m ${s}s';
    return '${s}s';
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        const Icon(Icons.schedule_rounded, size: 12, color: AppColors.ember),
        const SizedBox(width: 3),
        Text(
          _formatted,
          style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            color: AppColors.ember,
          ),
        ),
      ],
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Won Tab
// ══════════════════════════════════════════════════════════════════

class _WonTab extends StatelessWidget {
  const _WonTab({
    super.key,
    required this.bids,
    required this.onRefresh,
  });

  final List<WonBid> bids;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (bids.isEmpty) {
      return _EmptyState(
        icon: Icons.emoji_events_rounded,
        title: S.of(context).noWinsYet,
        titleAr: 'لم تفز بأي مزاد بعد',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(
          top: AppSpacing.xs,
          bottom: AppSpacing.xxxl,
        ),
        itemCount: bids.length,
        itemBuilder: (_, i) => _WonBidCard(bid: bids[i]),
      ),
    );
  }
}

class _WonBidCard extends StatelessWidget {
  const _WonBidCard({required this.bid});
  final WonBid bid;

  (String label, Color color) get _escrowChip => switch (bid.escrowStatus) {
        'awaiting_payment' => ('Awaiting payment', AppColors.gold),
        'shipping' => ('Shipping', AppColors.navy),
        'in_transit' => ('In transit', AppColors.navy),
        'complete' => ('Complete', AppColors.emerald),
        _ => (bid.escrowStatus, AppColors.mist),
      };

  @override
  Widget build(BuildContext context) {
    final escrow = _escrowChip;
    final awaitingPayment = bid.escrowStatus == 'awaiting_payment';

    return Container(
      margin: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xxs + 2,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Padding(
        padding: AppSpacing.allMd,
        child: Row(
          children: [
            // Image
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: CachedNetworkImage(
                imageUrl: bid.imageUrl,
                width: 60,
                height: 60,
                fit: BoxFit.cover,
                placeholder: (_, __) =>
                    Container(width: 60, height: 60, color: AppColors.sand),
                errorWidget: (_, __, ___) => Container(
                  width: 60,
                  height: 60,
                  color: AppColors.sand,
                  child:
                      const Icon(Icons.image, color: AppColors.mist, size: 20),
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),

            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Won badge
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: AppColors.emerald.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Text(
                      'Won! \u2713',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        color: AppColors.emerald,
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    bid.titleEn,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    ArabicNumerals.formatCurrencyEn(
                        bid.finalPrice, bid.currency),
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 5),
                  // Escrow status chip
                  Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                    decoration: BoxDecoration(
                      color: escrow.$2.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      escrow.$1,
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 10,
                        fontWeight: FontWeight.w600,
                        color: escrow.$2,
                      ),
                    ),
                  ),
                  // Payment deadline timer
                  if (awaitingPayment && bid.paymentDeadline != null) ...[
                    const SizedBox(height: 4),
                    _CountdownTimer(endsAt: bid.paymentDeadline!),
                  ],
                ],
              ),
            ),

            // Action
            Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (awaitingPayment)
                  GestureDetector(
                    onTap: () => context.push('/escrow/${bid.escrowId}'),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 6,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.gold,
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: const Text(
                        'Pay now',
                        style: TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: Colors.white,
                        ),
                      ),
                    ),
                  )
                else
                  GestureDetector(
                    onTap: () => context.push('/escrow/${bid.escrowId}'),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: AppColors.navy.withOpacity(0.08),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Text(
                        'View order',
                        style: TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: AppColors.navy,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Lost Tab
// ══════════════════════════════════════════════════════════════════

class _LostTab extends StatelessWidget {
  const _LostTab({
    super.key,
    required this.bids,
    required this.onRefresh,
  });

  final List<LostBid> bids;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (bids.isEmpty) {
      return _EmptyState(
        icon: Icons.sentiment_neutral_rounded,
        title: S.of(context).noLostBids,
        titleAr: 'لا توجد مزايدات خاسرة',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(
          top: AppSpacing.xs,
          bottom: AppSpacing.xxxl,
        ),
        itemCount: bids.length,
        itemBuilder: (_, i) => _LostBidCard(bid: bids[i]),
      ),
    );
  }
}

class _LostBidCard extends StatelessWidget {
  const _LostBidCard({required this.bid});
  final LostBid bid;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xxs + 2,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Padding(
        padding: AppSpacing.allMd,
        child: Row(
          children: [
            // Image — slightly desaturated
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: ColorFiltered(
                colorFilter: const ColorFilter.mode(
                  Colors.white24,
                  BlendMode.lighten,
                ),
                child: CachedNetworkImage(
                  imageUrl: bid.imageUrl,
                  width: 60,
                  height: 60,
                  fit: BoxFit.cover,
                  placeholder: (_, __) =>
                      Container(width: 60, height: 60, color: AppColors.sand),
                  errorWidget: (_, __, ___) => Container(
                    width: 60,
                    height: 60,
                    color: AppColors.sand,
                    child: const Icon(Icons.image,
                        color: AppColors.mist, size: 20),
                  ),
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),

            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    bid.titleEn,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  const SizedBox(height: 3),
                  Text(
                    'Final: ${ArabicNumerals.formatCurrencyEn(bid.finalPrice, bid.currency)}',
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'Won by ${bid.winnerMasked}',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.mist,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'Your bid: ${ArabicNumerals.formatCurrencyEn(bid.yourAmount, bid.currency)}',
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.mist,
                    ),
                  ),
                ],
              ),
            ),

            // Find similar
            GestureDetector(
              onTap: () {
                // Navigate to search with category pre-applied
                context.push(
                  AppRoutes.search,
                  extra: {'categoryId': bid.category},
                );
              },
              child: Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                decoration: BoxDecoration(
                  color: AppColors.gold,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: const Text(
                  'Find similar',
                  style: TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Watchlist Tab
// ══════════════════════════════════════════════════════════════════

class _WatchlistTab extends StatelessWidget {
  const _WatchlistTab({
    super.key,
    required this.items,
    required this.onRefresh,
    required this.onRemove,
  });

  final List<WatchlistItem> items;
  final Future<void> Function() onRefresh;
  final ValueChanged<WatchlistItem> onRemove;

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) {
      return _EmptyState(
        icon: Icons.favorite_border_rounded,
        title: S.of(context).watchlistEmpty,
        titleAr: 'قائمة المراقبة فارغة',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(
          top: AppSpacing.xs,
          bottom: AppSpacing.xxxl,
        ),
        itemCount: items.length,
        itemBuilder: (_, i) => _WatchlistCard(
          item: items[i],
          onRemove: () => onRemove(items[i]),
        ),
      ),
    );
  }
}

class _WatchlistCard extends StatelessWidget {
  const _WatchlistCard({
    required this.item,
    required this.onRemove,
  });

  final WatchlistItem item;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xxs + 2,
      ),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Stack(
        children: [
          Padding(
            padding: AppSpacing.allMd,
            child: Row(
              children: [
                // Image
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: CachedNetworkImage(
                    imageUrl: item.imageUrl,
                    width: 60,
                    height: 60,
                    fit: BoxFit.cover,
                    placeholder: (_, __) =>
                        Container(width: 60, height: 60, color: AppColors.sand),
                    errorWidget: (_, __, ___) => Container(
                      width: 60,
                      height: 60,
                      color: AppColors.sand,
                      child: const Icon(Icons.image,
                          color: AppColors.mist, size: 20),
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),

                // Info
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item.titleEn,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink,
                        ),
                      ),
                      const SizedBox(height: 3),
                      Text(
                        ArabicNumerals.formatCurrencyEn(
                          item.currentPrice,
                          item.currency,
                        ),
                        style: const TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.navy,
                        ),
                      ),
                      const SizedBox(height: 3),
                      if (item.bidCount > 0)
                        Text(
                          '${item.bidCount} bids',
                          style: const TextStyle(
                            fontSize: 11,
                            color: AppColors.mist,
                          ),
                        ),
                      if (item.endsAt != null)
                        _CountdownTimer(endsAt: item.endsAt!),
                    ],
                  ),
                ),

                // Bid now
                GestureDetector(
                  onTap: () =>
                      context.push('/listing/${item.listingId}'),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.navy,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: const Text(
                      'Bid now',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),

          // Heart remove button
          PositionedDirectional(
            top: 8,
            end: 8,
            child: GestureDetector(
              onTap: onRemove,
              child: const Icon(
                Icons.favorite_rounded,
                color: AppColors.ember,
                size: 22,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Empty state
// ══════════════════════════════════════════════════════════════════

class _EmptyState extends StatelessWidget {
  const _EmptyState({
    required this.icon,
    required this.title,
    required this.titleAr,
  });

  final IconData icon;
  final String title;
  final String titleAr;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: AppSpacing.allXl,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 80,
              height: 80,
              decoration: BoxDecoration(
                color: AppColors.sand.withOpacity(0.6),
                shape: BoxShape.circle,
              ),
              child: Icon(icon, size: 36, color: AppColors.mist),
            ),
            const SizedBox(height: AppSpacing.lg),
            Text(
              title,
              style: const TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.navy,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              titleAr,
              style: const TextStyle(fontSize: 14, color: AppColors.mist),
              textDirection: TextDirection.rtl,
            ),
          ],
        ),
      ),
    );
  }
}
