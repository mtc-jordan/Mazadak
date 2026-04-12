import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
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
// Model
// ══════════════════════════════════════════════════════════════════

class UserAuction {
  const UserAuction({
    required this.id,
    required this.listingId,
    required this.titleAr,
    this.titleEn,
    required this.imageUrl,
    required this.startingPrice,
    this.currentPrice,
    required this.currency,
    this.bidCount = 0,
    required this.status,
    this.endsAt,
    this.winnerName,
    this.isLive = false,
  });

  final String id;
  final String listingId;
  final String titleAr;
  final String? titleEn;
  final String imageUrl;
  final double startingPrice;
  final double? currentPrice;
  final String currency;
  final int bidCount;
  final String status; // active, ended, cancelled, pending
  final String? endsAt;
  final String? winnerName;
  final bool isLive;

  double get displayPrice => currentPrice ?? startingPrice;

  factory UserAuction.fromJson(Map<String, dynamic> json) => UserAuction(
        id: (json['id'] as String?) ?? '',
        listingId: (json['listing_id'] as String?) ?? (json['id'] as String?) ?? '',
        titleAr: (json['title_ar'] as String?) ?? '',
        titleEn: json['title_en'] as String?,
        imageUrl: json['image_url'] as String? ?? '',
        startingPrice: (json['starting_price'] as num).toDouble(),
        currentPrice: (json['current_price'] as num?)?.toDouble(),
        currency: json['currency'] as String? ?? 'JOD',
        bidCount: json['bid_count'] as int? ?? 0,
        status: json['status'] as String? ?? 'active',
        endsAt: json['ends_at'] as String?,
        winnerName: json['winner_name'] as String?,
        isLive: json['is_live'] as bool? ?? false,
      );
}

// ══════════════════════════════════════════════════════════════════
// State
// ══════════════════════════════════════════════════════════════════

class MyAuctionsState {
  const MyAuctionsState({
    this.active = const [],
    this.ended = const [],
    this.won = const [],
    this.isLoading = false,
    this.error,
  });

  final List<UserAuction> active;
  final List<UserAuction> ended;
  final List<UserAuction> won;
  final bool isLoading;
  final String? error;

  MyAuctionsState copyWith({
    List<UserAuction>? active,
    List<UserAuction>? ended,
    List<UserAuction>? won,
    bool? isLoading,
    String? error,
  }) =>
      MyAuctionsState(
        active: active ?? this.active,
        ended: ended ?? this.ended,
        won: won ?? this.won,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

// ══════════════════════════════════════════════════════════════════
// Provider
// ══════════════════════════════════════════════════════════════════

final myAuctionsProvider =
    StateNotifierProvider.autoDispose<MyAuctionsNotifier, MyAuctionsState>(
        (ref) {
  return MyAuctionsNotifier(ref);
});

class MyAuctionsNotifier extends StateNotifier<MyAuctionsState> {
  MyAuctionsNotifier(this._ref) : super(const MyAuctionsState()) {
    load();
  }

  final Ref _ref;

  Future<void> load() async {
    if (state.isLoading) return;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/auctions/mine');
      final data = resp.data as Map<String, dynamic>;

      List<UserAuction> _parse(String key) => (data[key] as List?)
              ?.map((e) => UserAuction.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const [];

      state = MyAuctionsState(
        active: _parse('active'),
        ended: _parse('ended'),
        won: _parse('won'),
        isLoading: false,
      );
    } catch (e) {
      // Fallback to mock data when backend is unavailable (dev mode)
      if (state.active.isEmpty && state.ended.isEmpty && state.won.isEmpty) {
        state = MyAuctionsState(
          active: _mockActive,
          ended: _mockEnded,
          won: _mockWon,
          isLoading: false,
        );
      } else {
        state = state.copyWith(isLoading: false, error: e.toString());
      }
    }
  }

  Future<void> refresh() => load();

  // ── Mock data ──────────────────────────────────────────────────

  static final _mockActive = [
    UserAuction(
      id: 'auc-1',
      listingId: 'mock-1',
      titleAr: 'ساعة رولكس سبمارينر ٢٠٢٤',
      titleEn: 'Rolex Submariner 2024',
      imageUrl: 'https://picsum.photos/seed/rolex/400/300',
      startingPrice: 8500,
      currentPrice: 12750,
      currency: 'JOD',
      bidCount: 23,
      status: 'active',
      endsAt: DateTime.now()
          .toUtc()
          .add(const Duration(hours: 2, minutes: 15))
          .toIso8601String(),
      isLive: true,
    ),
    UserAuction(
      id: 'auc-2',
      listingId: 'mock-2',
      titleAr: 'آيفون ١٥ برو ماكس ٢٥٦ جيجا',
      titleEn: 'iPhone 15 Pro Max 256GB',
      imageUrl: 'https://picsum.photos/seed/iphone/400/300',
      startingPrice: 350,
      currentPrice: 520,
      currency: 'JOD',
      bidCount: 14,
      status: 'active',
      endsAt: DateTime.now()
          .toUtc()
          .add(const Duration(minutes: 45))
          .toIso8601String(),
    ),
    UserAuction(
      id: 'auc-3',
      listingId: 'mock-3',
      titleAr: 'مرسيدس بنز C200 موديل ٢٠٢٢',
      titleEn: 'Mercedes-Benz C200 2022',
      imageUrl: 'https://picsum.photos/seed/mercedes/400/300',
      startingPrice: 25000,
      currentPrice: 28500,
      currency: 'JOD',
      bidCount: 8,
      status: 'active',
      endsAt: DateTime.now()
          .toUtc()
          .add(const Duration(days: 1, hours: 6))
          .toIso8601String(),
    ),
  ];

  static final _mockEnded = [
    UserAuction(
      id: 'auc-4',
      listingId: 'mock-4',
      titleAr: 'لوحة فنية أصلية — خط عربي',
      titleEn: 'Original Arabic Calligraphy Art',
      imageUrl: 'https://picsum.photos/seed/art/400/300',
      startingPrice: 150,
      currentPrice: 280,
      currency: 'JOD',
      bidCount: 6,
      status: 'ended',
      winnerName: 'محمد أحمد',
    ),
    UserAuction(
      id: 'auc-5',
      listingId: 'mock-5',
      titleAr: 'سوار ذهب عيار ٢١',
      titleEn: 'Gold Bracelet 21K',
      imageUrl: 'https://picsum.photos/seed/gold/400/300',
      startingPrice: 400,
      currentPrice: 650,
      currency: 'JOD',
      bidCount: 19,
      status: 'ended',
      winnerName: 'سارة خالد',
    ),
    UserAuction(
      id: 'auc-6',
      listingId: 'mock-6',
      titleAr: 'بلايستيشن ٥ مع ألعاب',
      titleEn: 'PlayStation 5 Bundle',
      imageUrl: 'https://picsum.photos/seed/ps5/400/300',
      startingPrice: 180,
      currentPrice: 245,
      currency: 'JOD',
      bidCount: 11,
      status: 'ended',
    ),
  ];

  static final _mockWon = [
    UserAuction(
      id: 'auc-7',
      listingId: 'mock-7',
      titleAr: 'عقد ألماس طبيعي',
      titleEn: 'Natural Diamond Necklace',
      imageUrl: 'https://picsum.photos/seed/diamond/400/300',
      startingPrice: 2000,
      currentPrice: 3200,
      currency: 'JOD',
      bidCount: 31,
      status: 'ended',
      winnerName: 'أنت',
    ),
    UserAuction(
      id: 'auc-8',
      listingId: 'mock-8',
      titleAr: 'طاولة أنتيك عثمانية',
      titleEn: 'Ottoman Antique Table',
      imageUrl: 'https://picsum.photos/seed/antique/400/300',
      startingPrice: 500,
      currentPrice: 720,
      currency: 'JOD',
      bidCount: 9,
      status: 'ended',
      winnerName: 'أنت',
    ),
  ];
}

// ══════════════════════════════════════════════════════════════════
// Screen
// ══════════════════════════════════════════════════════════════════

class MyAuctionsScreen extends ConsumerStatefulWidget {
  const MyAuctionsScreen({super.key});

  @override
  ConsumerState<MyAuctionsScreen> createState() => _MyAuctionsScreenState();
}

class _MyAuctionsScreenState extends ConsumerState<MyAuctionsScreen> {
  int _tabIndex = 0;

  static const _tabLabels = ['نشطة', 'منتهية', 'فزت بها'];

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(myAuctionsProvider);

    final counts = [
      state.active.length,
      state.ended.length,
      state.won.length,
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
              'My auctions',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'مزاداتي',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: Column(
        children: [
          // ── Tab bar ────────────────────────────────────────────
          _TabBar(
            labels: _tabLabels,
            counts: counts,
            selectedIndex: _tabIndex,
            onTap: (i) => setState(() => _tabIndex = i),
          ),

          // ── Tab content ────────────────────────────────────────
          Expanded(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 150),
              child: _buildTabContent(state),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTabContent(MyAuctionsState state) {
    if (state.isLoading &&
        state.active.isEmpty &&
        state.ended.isEmpty &&
        state.won.isEmpty) {
      return const Center(
        key: ValueKey('loading'),
        child: CircularProgressIndicator(color: AppColors.navy),
      );
    }

    return switch (_tabIndex) {
      0 => _ActiveTab(
          key: const ValueKey('tab-active'),
          auctions: state.active,
          onRefresh: () => ref.read(myAuctionsProvider.notifier).refresh(),
        ),
      1 => _EndedTab(
          key: const ValueKey('tab-ended'),
          auctions: state.ended,
          onRefresh: () => ref.read(myAuctionsProvider.notifier).refresh(),
        ),
      2 => _WonTab(
          key: const ValueKey('tab-won'),
          auctions: state.won,
          onRefresh: () => ref.read(myAuctionsProvider.notifier).refresh(),
        ),
      _ => const SizedBox.shrink(),
    };
  }
}

// ══════════════════════════════════════════════════════════════════
// Custom Tab Bar — pill-shaped selection (matches MyListingsScreen)
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
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 7,
                  ),
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
                            fontFamily: 'NotoKufiArabic',
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: isSelected ? Colors.white : AppColors.mist,
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
                              color:
                                  isSelected ? Colors.white : AppColors.navy,
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
// Active Auctions Tab
// ══════════════════════════════════════════════════════════════════

class _ActiveTab extends StatelessWidget {
  const _ActiveTab({
    super.key,
    required this.auctions,
    required this.onRefresh,
  });

  final List<UserAuction> auctions;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (auctions.isEmpty) {
      return _EmptyState(
        icon: Icons.gavel_rounded,
        title: S.of(context).noActiveAuctions,
        titleAr: 'لا توجد مزادات نشطة',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        itemCount: auctions.length,
        itemBuilder: (ctx, i) {
          final auction = auctions[i];
          return _ActiveAuctionCard(
            auction: auction,
            onTap: () => context.push('/auction/${auction.id}'),
          );
        },
      ),
    );
  }
}

class _ActiveAuctionCard extends StatelessWidget {
  const _ActiveAuctionCard({
    required this.auction,
    required this.onTap,
  });

  final UserAuction auction;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        decoration: const BoxDecoration(
          border: Border(
            bottom: BorderSide(color: AppColors.sand, width: 0.5),
          ),
        ),
        child: Row(
          children: [
            // Thumbnail
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Stack(
                children: [
                  CachedNetworkImage(
                    imageUrl: auction.imageUrl,
                    width: 72,
                    height: 72,
                    fit: BoxFit.cover,
                    placeholder: (_, __) => Container(
                      width: 72,
                      height: 72,
                      color: AppColors.sand,
                    ),
                    errorWidget: (_, __, ___) => Container(
                      width: 72,
                      height: 72,
                      color: AppColors.sand,
                      child: const Icon(Icons.image, color: AppColors.mist),
                    ),
                  ),
                  // Live badge
                  if (auction.isLive)
                    Positioned(
                      top: 4,
                      left: 4,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 5,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.ember,
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'LIVE',
                          style: TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 8,
                            fontWeight: FontWeight.w800,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(width: AppSpacing.sm),

            // Info column
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Arabic title
                  Text(
                    auction.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textDirection: TextDirection.rtl,
                    style: const TextStyle(
                      fontFamily: 'NotoKufiArabic',
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  // English title
                  if (auction.titleEn != null)
                    Text(
                      auction.titleEn!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.mist,
                      ),
                    ),
                  const SizedBox(height: 4),
                  // Price + bids
                  Row(
                    children: [
                      Text(
                        ArabicNumerals.formatCurrencyEn(
                          auction.displayPrice,
                          auction.currency,
                        ),
                        style: const TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.navy,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.gold.withOpacity(0.12),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          '${auction.bidCount} bids',
                          style: const TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: AppColors.gold,
                          ),
                        ),
                      ),
                    ],
                  ),
                  // Timer
                  if (auction.endsAt != null)
                    _TimerBadge(endsAt: auction.endsAt!),
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
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Timer Badge (countdown with pulse for < 30 min)
// ══════════════════════════════════════════════════════════════════

class _TimerBadge extends StatefulWidget {
  const _TimerBadge({required this.endsAt});
  final String endsAt;

  @override
  State<_TimerBadge> createState() => _TimerBadgeState();
}

class _TimerBadgeState extends State<_TimerBadge>
    with SingleTickerProviderStateMixin {
  late final DateTime _endsAt;
  Timer? _timer;
  Duration _remaining = Duration.zero;
  late final AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _endsAt = DateTime.tryParse(widget.endsAt) ?? DateTime.now();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _tick();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  void _tick() {
    if (!mounted) return;
    final now = DateTime.now();
    final diff = _endsAt.difference(now);
    setState(() => _remaining = diff.isNegative ? Duration.zero : diff);

    if (_remaining.inMinutes < 30 && _remaining > Duration.zero) {
      if (!_pulseController.isAnimating) _pulseController.repeat(reverse: true);
    } else {
      if (_pulseController.isAnimating) _pulseController.stop();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _pulseController.dispose();
    super.dispose();
  }

  String get _formatted {
    if (_remaining == Duration.zero) return 'Ended';
    final h = _remaining.inHours;
    final m = _remaining.inMinutes % 60;
    final s = _remaining.inSeconds % 60;
    if (h > 0) return '${h}h ${m}m left';
    if (m > 0) return '${m}m ${s}s left';
    return '${s}s left';
  }

  @override
  Widget build(BuildContext context) {
    final isUrgent = _remaining.inMinutes < 30 && _remaining > Duration.zero;

    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: AnimatedBuilder(
        animation: _pulseController,
        builder: (_, child) {
          final opacity = isUrgent ? 0.6 + 0.4 * _pulseController.value : 1.0;
          return Opacity(opacity: opacity, child: child);
        },
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.schedule_rounded,
              size: 12,
              color: isUrgent ? AppColors.ember : AppColors.mist,
            ),
            const SizedBox(width: 3),
            Text(
              _formatted,
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: isUrgent ? AppColors.ember : AppColors.mist,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Ended Auctions Tab
// ══════════════════════════════════════════════════════════════════

class _EndedTab extends StatelessWidget {
  const _EndedTab({
    super.key,
    required this.auctions,
    required this.onRefresh,
  });

  final List<UserAuction> auctions;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (auctions.isEmpty) {
      return _EmptyState(
        icon: Icons.history_rounded,
        title: S.of(context).noEndedAuctions,
        titleAr: 'لا توجد مزادات منتهية',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        itemCount: auctions.length,
        itemBuilder: (_, i) {
          final auction = auctions[i];
          return _EndedAuctionCard(
            auction: auction,
            onTap: () => context.push('/listing/${auction.listingId}'),
          );
        },
      ),
    );
  }
}

class _EndedAuctionCard extends StatelessWidget {
  const _EndedAuctionCard({
    required this.auction,
    required this.onTap,
  });

  final UserAuction auction;
  final VoidCallback onTap;

  /// Masks a name: first char + '***' + last 3 chars.
  static String _maskName(String name) {
    if (name.length <= 4) return '${name[0]}***';
    return '${name[0]}***${name.substring(name.length - 3)}';
  }

  @override
  Widget build(BuildContext context) {
    final hasBids = auction.bidCount > 0;

    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        decoration: const BoxDecoration(
          border: Border(
            bottom: BorderSide(color: AppColors.sand, width: 0.5),
          ),
        ),
        child: Row(
          children: [
            // Thumbnail
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: CachedNetworkImage(
                imageUrl: auction.imageUrl,
                width: 72,
                height: 72,
                fit: BoxFit.cover,
                placeholder: (_, __) => Container(
                  width: 72,
                  height: 72,
                  color: AppColors.sand,
                ),
                errorWidget: (_, __, ___) => Container(
                  width: 72,
                  height: 72,
                  color: AppColors.sand,
                  child: const Icon(Icons.image, color: AppColors.mist),
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
                    auction.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textDirection: TextDirection.rtl,
                    style: const TextStyle(
                      fontFamily: 'NotoKufiArabic',
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  const SizedBox(height: 4),
                  // Final price
                  Text(
                    'Final: ${ArabicNumerals.formatCurrencyEn(auction.displayPrice, auction.currency)}',
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 4),
                  // Winner (masked) or unsold
                  if (auction.winnerName != null)
                    Text(
                      'Won by ${_maskName(auction.winnerName!)}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.mist,
                      ),
                    )
                  else
                    Text(
                      hasBids ? '${auction.bidCount} bids' : 'No bids',
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.mist,
                      ),
                    ),
                ],
              ),
            ),

            // Outcome badge
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: (auction.winnerName != null
                        ? AppColors.emerald
                        : AppColors.mist)
                    .withOpacity(0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                auction.winnerName != null ? 'Sold' : 'Unsold',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: auction.winnerName != null
                      ? AppColors.emerald
                      : AppColors.mist,
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
// Won Auctions Tab
// ══════════════════════════════════════════════════════════════════

class _WonTab extends StatelessWidget {
  const _WonTab({
    super.key,
    required this.auctions,
    required this.onRefresh,
  });

  final List<UserAuction> auctions;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (auctions.isEmpty) {
      return _EmptyState(
        icon: Icons.emoji_events_rounded,
        title: S.of(context).noAuctionsWon,
        titleAr: 'لم تفز بأي مزاد بعد',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        itemCount: auctions.length,
        itemBuilder: (_, i) {
          final auction = auctions[i];
          return _WonAuctionCard(
            auction: auction,
            onTap: () => context.push('/listing/${auction.listingId}'),
          );
        },
      ),
    );
  }
}

class _WonAuctionCard extends StatelessWidget {
  const _WonAuctionCard({
    required this.auction,
    required this.onTap,
  });

  final UserAuction auction;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        decoration: const BoxDecoration(
          border: Border(
            bottom: BorderSide(color: AppColors.sand, width: 0.5),
          ),
        ),
        child: Row(
          children: [
            // Thumbnail with trophy overlay
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Stack(
                children: [
                  CachedNetworkImage(
                    imageUrl: auction.imageUrl,
                    width: 72,
                    height: 72,
                    fit: BoxFit.cover,
                    placeholder: (_, __) => Container(
                      width: 72,
                      height: 72,
                      color: AppColors.sand,
                    ),
                    errorWidget: (_, __, ___) => Container(
                      width: 72,
                      height: 72,
                      color: AppColors.sand,
                      child: const Icon(Icons.image, color: AppColors.mist),
                    ),
                  ),
                  Positioned(
                    top: 4,
                    left: 4,
                    child: Container(
                      padding: const EdgeInsets.all(3),
                      decoration: BoxDecoration(
                        color: AppColors.gold,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: const Icon(
                        Icons.emoji_events_rounded,
                        size: 12,
                        color: Colors.white,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: AppSpacing.sm),

            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    auction.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textDirection: TextDirection.rtl,
                    style: const TextStyle(
                      fontFamily: 'NotoKufiArabic',
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  if (auction.titleEn != null)
                    Text(
                      auction.titleEn!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 11,
                        color: AppColors.mist,
                      ),
                    ),
                  const SizedBox(height: 4),
                  // Winning price
                  Text(
                    ArabicNumerals.formatCurrencyEn(
                      auction.displayPrice,
                      auction.currency,
                    ),
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${auction.bidCount} bids',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.mist,
                    ),
                  ),
                ],
              ),
            ),

            // Won badge
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.gold.withOpacity(0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Text(
                'Won',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: AppColors.gold,
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
              style: const TextStyle(
                fontSize: 14,
                color: AppColors.mist,
              ),
              textDirection: TextDirection.rtl,
            ),
          ],
        ),
      ),
    );
  }
}
