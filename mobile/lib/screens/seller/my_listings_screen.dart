import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:dio/dio.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/core_providers.dart';
import '../../core/providers/listings_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import '../../widgets/mzadak_refresh_indicator.dart';

// ══════════════════════════════════════════════════════════════════
// Provider — fetches seller's own listings grouped by status
// ══════════════════════════════════════════════════════════════════

class MyListingsState {
  const MyListingsState({
    this.active = const [],
    this.ended = const [],
    this.draft = const [],
    this.pending = const [],
    this.isLoading = false,
    this.error,
  });

  final List<ListingSummary> active;
  final List<ListingSummary> ended;
  final List<ListingSummary> draft;
  final List<ListingSummary> pending;
  final bool isLoading;
  final String? error;

  MyListingsState copyWith({
    List<ListingSummary>? active,
    List<ListingSummary>? ended,
    List<ListingSummary>? draft,
    List<ListingSummary>? pending,
    bool? isLoading,
    String? error,
  }) =>
      MyListingsState(
        active: active ?? this.active,
        ended: ended ?? this.ended,
        draft: draft ?? this.draft,
        pending: pending ?? this.pending,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

final myListingsProvider =
    StateNotifierProvider.autoDispose<MyListingsNotifier, MyListingsState>(
        (ref) {
  return MyListingsNotifier(ref);
});

class MyListingsNotifier extends StateNotifier<MyListingsState> {
  MyListingsNotifier(this._ref) : super(const MyListingsState()) {
    load();
  }

  final Ref _ref;

  Future<void> load() async {
    if (state.isLoading) return;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/listings/mine');
      final data = resp.data as Map<String, dynamic>;

      List<ListingSummary> _parse(String key) => (data[key] as List?)
              ?.map((e) => ListingSummary.fromJson(e as Map<String, dynamic>))
              .toList() ??
          const [];

      state = MyListingsState(
        active: _parse('active'),
        ended: _parse('ended'),
        draft: _parse('draft'),
        pending: _parse('pending'),
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> refresh() => load();

  Future<void> endEarly(String listingId) async {
    try {
      final api = _ref.read(apiClientProvider);
      await api.post('/listings/$listingId/end');
      await load();
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }
}

// ══════════════════════════════════════════════════════════════════
// Screen
// ══════════════════════════════════════════════════════════════════

class MyListingsScreen extends ConsumerStatefulWidget {
  const MyListingsScreen({super.key});

  @override
  ConsumerState<MyListingsScreen> createState() => _MyListingsScreenState();
}

class _MyListingsScreenState extends ConsumerState<MyListingsScreen>
    with SingleTickerProviderStateMixin {
  int _tabIndex = 0;

  static const _tabLabels = ['Active', 'Ended', 'Draft', 'Pending review'];

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(myListingsProvider);

    final counts = [
      state.active.length,
      state.ended.length,
      state.draft.length,
      state.pending.length,
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
              'My listings',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'إعلاناتي',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        centerTitle: true,
        actions: [
          Padding(
            padding: const EdgeInsetsDirectional.only(end: AppSpacing.sm),
            child: GestureDetector(
              onTap: () => context.push(AppRoutes.snapToList),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: AppColors.gold,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'New',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
                      ),
                    ),
                    SizedBox(width: 2),
                    Icon(Icons.add_rounded, color: Colors.white, size: 16),
                  ],
                ),
              ),
            ),
          ),
        ],
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

  Widget _buildTabContent(MyListingsState state) {
    if (state.isLoading && state.active.isEmpty) {
      return const Center(
        key: ValueKey('loading'),
        child: CircularProgressIndicator(color: AppColors.navy),
      );
    }

    return switch (_tabIndex) {
      0 => _ActiveTab(
          key: const ValueKey('tab-active'),
          listings: state.active,
          onRefresh: () => ref.read(myListingsProvider.notifier).refresh(),
          onEndEarly: (id) =>
              ref.read(myListingsProvider.notifier).endEarly(id),
        ),
      1 => _EndedTab(
          key: const ValueKey('tab-ended'),
          listings: state.ended,
          onRefresh: () => ref.read(myListingsProvider.notifier).refresh(),
        ),
      2 => _DraftTab(
          key: const ValueKey('tab-draft'),
          listings: state.draft,
          onRefresh: () => ref.read(myListingsProvider.notifier).refresh(),
        ),
      3 => _PendingTab(
          key: const ValueKey('tab-pending'),
          listings: state.pending,
          onRefresh: () => ref.read(myListingsProvider.notifier).refresh(),
        ),
      _ => const SizedBox.shrink(),
    };
  }
}

// ══════════════════════════════════════════════════════════════════
// Custom Tab Bar — pill-shaped selection
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
                            fontFamily: 'Sora',
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
// Active Listings Tab
// ══════════════════════════════════════════════════════════════════

class _ActiveTab extends StatelessWidget {
  const _ActiveTab({
    super.key,
    required this.listings,
    required this.onRefresh,
    required this.onEndEarly,
  });

  final List<ListingSummary> listings;
  final Future<void> Function() onRefresh;
  final ValueChanged<String> onEndEarly;

  @override
  Widget build(BuildContext context) {
    if (listings.isEmpty) {
      return _EmptyState(
        icon: Icons.storefront_rounded,
        title: 'No active listings',
        titleAr: 'لا توجد إعلانات نشطة',
        ctaLabel: 'Snap-to-List takes 60 seconds →',
        onCta: () => context.push(AppRoutes.snapToList),
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        itemCount: listings.length,
        itemBuilder: (ctx, i) {
          final listing = listings[i];
          return _ActiveListingCard(
            listing: listing,
            onTap: () => context.push('/listing/${listing.id}'),
            onMenu: () => _showMenu(ctx, listing),
          );
        },
      ),
    );
  }

  void _showMenu(BuildContext context, ListingSummary listing) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Drag handle
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.sm),
              child: Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.sand,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            if (listing.bidCount == 0)
              ListTile(
                leading:
                    const Icon(Icons.edit_rounded, color: AppColors.navy),
                title: const Text('Edit listing'),
                onTap: () {
                  Navigator.pop(context);
                  _tryEdit(context, listing);
                },
              ),
            ListTile(
              leading: const Icon(Icons.gavel_rounded, color: AppColors.ember),
              title: const Text('End early'),
              onTap: () {
                Navigator.pop(context);
                _confirmEndEarly(context, listing);
              },
            ),
            ListTile(
              leading: const Icon(Icons.share_rounded, color: AppColors.navy),
              title: const Text('Share'),
              onTap: () => Navigator.pop(context),
            ),
            ListTile(
              leading: const Icon(Icons.analytics_rounded,
                  color: AppColors.navy),
              title: const Text('View analytics'),
              onTap: () => Navigator.pop(context),
            ),
            const SizedBox(height: AppSpacing.xs),
          ],
        ),
      ),
    );
  }

  Future<void> _tryEdit(BuildContext context, ListingSummary listing) async {
    // Preflight check — verify listing still has 0 bids before allowing edit.
    // If bids arrived since the sheet was opened, API returns 400.
    try {
      final api = ProviderScope.containerOf(context).read(apiClientProvider);
      await api.get('/listings/${listing.id}/can-edit');
      if (context.mounted) {
        context.push('/listing/${listing.id}/edit');
      }
    } on DioException catch (e) {
      if (!context.mounted) return;
      if (e.response?.statusCode == 400) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Cannot edit listing with active bids'),
            backgroundColor: AppColors.ember,
          ),
        );
      }
    }
  }

  void _confirmEndEarly(BuildContext context, ListingSummary listing) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('End listing early?'),
        content: const Text(
          'This action cannot be undone. If there are bids, '
          'the highest bidder wins.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              onEndEarly(listing.id);
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.ember,
              foregroundColor: Colors.white,
            ),
            child: const Text('End now'),
          ),
        ],
      ),
    );
  }
}

class _ActiveListingCard extends StatelessWidget {
  const _ActiveListingCard({
    required this.listing,
    required this.onTap,
    required this.onMenu,
  });

  final ListingSummary listing;
  final VoidCallback onTap;
  final VoidCallback onMenu;

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
              child: CachedNetworkImage(
                imageUrl: listing.imageUrl,
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

            // Info column
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // English title
                  Text(
                    listing.titleEn ?? listing.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  // Arabic title
                  Text(
                    listing.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textDirection: TextDirection.rtl,
                    style: const TextStyle(
                      fontFamily: 'NotoKufiArabic',
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
                          listing.displayPrice,
                          listing.currency,
                        ),
                        style: const TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                          color: AppColors.navy,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      Text(
                        '${listing.bidCount} bids',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.mist,
                        ),
                      ),
                    ],
                  ),
                  // Timer
                  if (listing.endsAt != null)
                    _TimerBadge(endsAt: listing.endsAt!),
                ],
              ),
            ),

            // Menu
            GestureDetector(
              onTap: onMenu,
              behavior: HitTestBehavior.opaque,
              child: const Padding(
                padding: EdgeInsets.all(8),
                child: Icon(
                  Icons.more_vert_rounded,
                  color: AppColors.mist,
                  size: 20,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

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

    // Pulse if < 30 min
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
// Ended Listings Tab
// ══════════════════════════════════════════════════════════════════

class _EndedTab extends StatelessWidget {
  const _EndedTab({
    super.key,
    required this.listings,
    required this.onRefresh,
  });

  final List<ListingSummary> listings;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (listings.isEmpty) {
      return const _EmptyState(
        icon: Icons.history_rounded,
        title: 'No ended listings',
        titleAr: 'لا توجد إعلانات منتهية',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        itemCount: listings.length,
        itemBuilder: (_, i) {
          final listing = listings[i];
          return _EndedListingCard(
            listing: listing,
            onTap: () {
              // Navigate to escrow for sold items
              if (listing.status == 'sold') {
                context.push('/escrow/${listing.id}');
              }
            },
          );
        },
      ),
    );
  }
}

class _EndedListingCard extends StatelessWidget {
  const _EndedListingCard({
    required this.listing,
    required this.onTap,
  });

  final ListingSummary listing;
  final VoidCallback onTap;

  /// Masks a name: first char + '***' + last 3 chars.
  /// e.g. "موتاسم" → "م***اسم"
  static String _maskName(String name) {
    if (name.length <= 4) return '${name[0]}***';
    return '${name[0]}***${name.substring(name.length - 3)}';
  }

  (String label, Color color) get _outcomeBadge => switch (listing.status) {
        'sold' => ('Sold \u2713', AppColors.emerald),
        'relisted' => ('Relisted', AppColors.gold),
        _ => ('Unsold', AppColors.mist),
      };

  @override
  Widget build(BuildContext context) {
    final badge = _outcomeBadge;

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
                imageUrl: listing.imageUrl,
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
                    listing.titleEn ?? listing.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  const SizedBox(height: 4),
                  // Final price
                  Text(
                    'Final: ${ArabicNumerals.formatCurrencyEn(listing.displayPrice, listing.currency)}',
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 4),
                  // Winner (masked)
                  if (listing.status == 'sold' && listing.winnerName != null)
                    Text(
                      'Won by ${_maskName(listing.winnerName!)}',
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
                color: badge.$2.withOpacity(0.12),
                borderRadius: BorderRadius.circular(12),
              ),
              child: Text(
                badge.$1,
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                  color: badge.$2,
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
// Draft Tab
// ══════════════════════════════════════════════════════════════════

class _DraftTab extends StatelessWidget {
  const _DraftTab({
    super.key,
    required this.listings,
    required this.onRefresh,
  });

  final List<ListingSummary> listings;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (listings.isEmpty) {
      return const _EmptyState(
        icon: Icons.drafts_rounded,
        title: 'No drafts',
        titleAr: 'لا توجد مسودات',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        padding: const EdgeInsets.only(top: AppSpacing.xs),
        itemCount: listings.length,
        itemBuilder: (_, i) {
          final listing = listings[i];
          return _DraftListingCard(listing: listing);
        },
      ),
    );
  }
}

class _DraftListingCard extends StatelessWidget {
  const _DraftListingCard({required this.listing});

  final ListingSummary listing;

  /// Simulated completion from the listing's fields.
  double get _completionPercent {
    var filled = 0;
    const total = 5;
    if (listing.titleAr.isNotEmpty) filled++;
    if (listing.imageUrl.isNotEmpty) filled++;
    if (listing.startingPrice > 0) filled++;
    if (listing.condition.isNotEmpty) filled++;
    if (listing.endsAt != null) filled++;
    return filled / total;
  }

  @override
  Widget build(BuildContext context) {
    final percent = _completionPercent;

    return GestureDetector(
      onTap: () {
        // Resume draft — navigate to snap-to-list with draft data
        context.push(AppRoutes.snapToList, extra: {'draftId': listing.id});
      },
      behavior: HitTestBehavior.opaque,
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.md,
              vertical: AppSpacing.sm,
            ),
            child: Row(
              children: [
                // Thumbnail
                ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: listing.imageUrl.isNotEmpty
                      ? CachedNetworkImage(
                          imageUrl: listing.imageUrl,
                          width: 72,
                          height: 72,
                          fit: BoxFit.cover,
                          placeholder: (_, __) => Container(
                            width: 72,
                            height: 72,
                            color: AppColors.sand,
                          ),
                          errorWidget: (_, __, ___) => _draftPlaceholder(),
                        )
                      : _draftPlaceholder(),
                ),
                const SizedBox(width: AppSpacing.sm),

                // Info
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        listing.titleEn ?? listing.titleAr,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: listing.titleAr.isNotEmpty
                              ? AppColors.ink
                              : AppColors.mist,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '${(percent * 100).toInt()}% complete',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.mist,
                        ),
                      ),
                      const SizedBox(height: 6),
                      // Resume button
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 4,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.navy.withOpacity(0.08),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: const Text(
                          'Resume draft',
                          style: TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                            color: AppColors.navy,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),

                const Icon(
                  Icons.chevron_right_rounded,
                  color: AppColors.mist,
                  size: 20,
                ),
              ],
            ),
          ),

          // Completion bar
          Container(
            height: 4,
            margin: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            decoration: BoxDecoration(
              color: AppColors.sand,
              borderRadius: BorderRadius.circular(2),
            ),
            alignment: Alignment.centerLeft,
            child: FractionallySizedBox(
              widthFactor: percent,
              child: Container(
                decoration: BoxDecoration(
                  color: AppColors.gold,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
          ),

          // Divider
          const Padding(
            padding: EdgeInsets.only(top: AppSpacing.xs),
            child: Divider(height: 0.5, color: AppColors.sand),
          ),
        ],
      ),
    );
  }

  Widget _draftPlaceholder() => Container(
        width: 72,
        height: 72,
        color: AppColors.sand,
        child: const Icon(Icons.photo_camera_rounded, color: AppColors.mist),
      );
}

// ══════════════════════════════════════════════════════════════════
// Pending Review Tab
// ══════════════════════════════════════════════════════════════════

class _PendingTab extends StatelessWidget {
  const _PendingTab({
    super.key,
    required this.listings,
    required this.onRefresh,
  });

  final List<ListingSummary> listings;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    if (listings.isEmpty) {
      return const _EmptyState(
        icon: Icons.hourglass_top_rounded,
        title: 'No pending reviews',
        titleAr: 'لا توجد مراجعات معلّقة',
      );
    }

    return MzadakRefreshIndicator(
      onRefresh: onRefresh,
      child: Column(
        children: [
          // Estimated time notice
          Container(
            width: double.infinity,
            margin: const EdgeInsets.fromLTRB(
              AppSpacing.md,
              AppSpacing.sm,
              AppSpacing.md,
              0,
            ),
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xs,
            ),
            decoration: BoxDecoration(
              color: const Color(0xFFFFF3E0), // amber tint
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Row(
              children: [
                Icon(Icons.schedule_rounded, size: 16, color: Color(0xFFE65100)),
                SizedBox(width: AppSpacing.xs),
                Text(
                  'Usually under 2 hours',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                    color: Color(0xFFE65100),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.only(top: AppSpacing.xs),
              itemCount: listings.length,
              itemBuilder: (_, i) {
                final listing = listings[i];
                return _PendingListingCard(
                  listing: listing,
                  onTap: () => _showPendingDetail(context, listing),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  void _showPendingDetail(BuildContext context, ListingSummary listing) {
    final isRejected = listing.status == 'rejected';

    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Padding(
          padding: AppSpacing.allLg,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Drag handle
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.sand,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
              Text(
                listing.titleEn ?? listing.titleAr,
                style: const TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              if (isRejected) ...[
                Container(
                  width: double.infinity,
                  padding: AppSpacing.allMd,
                  decoration: BoxDecoration(
                    color: AppColors.ember.withOpacity(0.08),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: const Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Rejection reason',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ember,
                        ),
                      ),
                      SizedBox(height: 4),
                      Text(
                        'Listing does not meet community guidelines. '
                        'Please review and resubmit.',
                        style: TextStyle(fontSize: 13, color: AppColors.ink),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: AppSpacing.md),
                SizedBox(
                  width: double.infinity,
                  height: 48,
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.pop(context);
                      context.push(AppRoutes.snapToList);
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.navy,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    child: const Text(
                      'Edit and resubmit',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ),
              ] else ...[
                const Text(
                  'Your listing is being reviewed by our team. '
                  'This usually takes under 2 hours.',
                  style: TextStyle(fontSize: 13, color: AppColors.mist),
                ),
              ],
              const SizedBox(height: AppSpacing.md),
            ],
          ),
        ),
      ),
    );
  }
}

class _PendingListingCard extends StatelessWidget {
  const _PendingListingCard({
    required this.listing,
    required this.onTap,
  });

  final ListingSummary listing;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final isRejected = listing.status == 'rejected';

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
                imageUrl: listing.imageUrl,
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

            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    listing.titleEn ?? listing.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    listing.titleAr,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textDirection: TextDirection.rtl,
                    style: const TextStyle(
                      fontFamily: 'NotoKufiArabic',
                      fontSize: 11,
                      color: AppColors.mist,
                    ),
                  ),
                  const SizedBox(height: 6),
                  // Badge
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 3,
                    ),
                    decoration: BoxDecoration(
                      color: isRejected
                          ? AppColors.ember.withOpacity(0.1)
                          : const Color(0xFFFFF3E0),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      isRejected ? 'Rejected' : 'Under review',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 10,
                        fontWeight: FontWeight.w700,
                        color: isRejected
                            ? AppColors.ember
                            : const Color(0xFFE65100),
                      ),
                    ),
                  ),
                ],
              ),
            ),

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
// Empty state
// ══════════════════════════════════════════════════════════════════

class _EmptyState extends StatelessWidget {
  const _EmptyState({
    required this.icon,
    required this.title,
    required this.titleAr,
    this.ctaLabel,
    this.onCta,
  });

  final IconData icon;
  final String title;
  final String titleAr;
  final String? ctaLabel;
  final VoidCallback? onCta;

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
            if (ctaLabel != null && onCta != null) ...[
              const SizedBox(height: AppSpacing.lg),
              GestureDetector(
                onTap: onCta,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 20,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.gold,
                    borderRadius: BorderRadius.circular(24),
                  ),
                  child: Text(
                    ctaLabel!,
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
