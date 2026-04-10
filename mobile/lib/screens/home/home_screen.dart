import 'dart:async';
import 'dart:math' as math;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shimmer/shimmer.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/providers/home_feed_provider.dart';
import '../../core/providers/listings_provider.dart';
import '../../core/providers/notification_provider.dart';
import '../../core/router.dart';
import '../../core/theme/animations.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import '../../widgets/listing_card.dart';
import '../../widgets/listing_card_skeleton.dart';

// ═══════════════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════════════

const _kBannerHeight = 190.0;
const _kBannerAutoAdvanceMs = 6000;
const _kLiveRotateMs = 5000;
const _kSearchHintCycleMs = 3000;
const _kCompactCardWidth = 148.0;
const _kCompactCardHeight = 210.0;
const _kWideThumbSize = 88.0;
const _kStaggerDelayMs = 40;

/// All 12 backend categories.
const _categories = <({String labelAr, String labelEn, int? id, IconData icon})>[
  (labelAr: 'الكل', labelEn: 'All', id: null, icon: Icons.grid_view_rounded),
  (labelAr: 'إلكترونيات', labelEn: 'Electronics', id: 1, icon: Icons.devices_rounded),
  (labelAr: 'سيارات', labelEn: 'Vehicles', id: 2, icon: Icons.directions_car_rounded),
  (labelAr: 'أثاث ومنزل', labelEn: 'Furniture', id: 3, icon: Icons.chair_rounded),
  (labelAr: 'أزياء', labelEn: 'Fashion', id: 4, icon: Icons.checkroom_rounded),
  (labelAr: 'مجوهرات', labelEn: 'Jewelry', id: 5, icon: Icons.diamond_rounded),
  (labelAr: 'مقتنيات', labelEn: 'Collectibles', id: 6, icon: Icons.collections_rounded),
  (labelAr: 'رياضة', labelEn: 'Sports', id: 7, icon: Icons.sports_soccer_rounded),
  (labelAr: 'عقارات', labelEn: 'Real Estate', id: 8, icon: Icons.home_work_rounded),
  (labelAr: 'كتب وفنون', labelEn: 'Art', id: 9, icon: Icons.palette_rounded),
  (labelAr: 'ألعاب', labelEn: 'Toys', id: 10, icon: Icons.toys_rounded),
  (labelAr: 'أعمال', labelEn: 'Business', id: 11, icon: Icons.business_center_rounded),
];

const _searchHints = ['ساعات فاخرة...', 'سيارات...', 'إلكترونيات...', 'مجوهرات...'];

// ═══════════════════════════════════════════════════════════════════
//  Home Screen
// ═══════════════════════════════════════════════════════════════════

class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen>
    with TickerProviderStateMixin {
  int _selectedCategory = 0;

  // ── Entrance animation ──────────────────────────────────────────
  late final AnimationController _entranceCtrl;
  late final Animation<double> _pillsFade;
  late final Animation<Offset> _bannerSlide;
  late final Animation<double> _bannerFade;

  // ── Search hint cycling ─────────────────────────────────────────
  int _searchHintIndex = 0;
  Timer? _searchHintTimer;

  // ── Pull-to-refresh spinner ─────────────────────────────────────
  late final AnimationController _refreshSpinCtrl;

  @override
  void initState() {
    super.initState();

    // Entrance orchestration (800ms total)
    _entranceCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _pillsFade = CurvedAnimation(
      parent: _entranceCtrl,
      curve: const Interval(0.0, 0.35, curve: Curves.easeOut),
    );
    _bannerSlide = Tween<Offset>(
      begin: const Offset(0, 0.08),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _entranceCtrl,
      curve: const Interval(0.12, 0.65, curve: AppAnimations.enterCurve),
    ));
    _bannerFade = CurvedAnimation(
      parent: _entranceCtrl,
      curve: const Interval(0.12, 0.55, curve: Curves.easeOut),
    );

    _refreshSpinCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );

    // Cycle search hints
    _searchHintTimer = Timer.periodic(
      const Duration(milliseconds: _kSearchHintCycleMs),
      (_) {
        if (mounted) {
          setState(() => _searchHintIndex = (_searchHintIndex + 1) % _searchHints.length);
        }
      },
    );

    // Start entrance after first frame
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _entranceCtrl.forward();
    });
  }

  @override
  void dispose() {
    _entranceCtrl.dispose();
    _refreshSpinCtrl.dispose();
    _searchHintTimer?.cancel();
    super.dispose();
  }

  Future<void> _onRefresh() async {
    _refreshSpinCtrl.repeat();
    await ref.read(homeFeedProvider.notifier).refresh();
    _refreshSpinCtrl.stop();
    _refreshSpinCtrl.reset();
  }

  void _onCategoryTap(int index) {
    if (_selectedCategory == index) return;
    HapticFeedback.selectionClick();
    setState(() => _selectedCategory = index);
    ref.read(homeFeedProvider.notifier).filterByCategory(_categories[index].id);
  }

  @override
  Widget build(BuildContext context) {
    final feed = ref.watch(homeFeedProvider);
    final isLoading = feed.isLoading && _hasNoData(feed);

    return RefreshIndicator(
      onRefresh: _onRefresh,
      color: AppColors.gold,
      backgroundColor: AppColors.cream,
      child: CustomScrollView(
        physics: const AlwaysScrollableScrollPhysics(
          parent: BouncingScrollPhysics(),
        ),
        slivers: [
          // ── 0. App Bar ──────────────────────────────────────────
          _MzadakAppBar(
            searchHintIndex: _searchHintIndex,
          ),

          // ── 1. Category Pills ───────────────────────────────────
          SliverToBoxAdapter(
            child: FadeTransition(
              opacity: _pillsFade,
              child: _CategoryRow(
                selected: _selectedCategory,
                onTap: _onCategoryTap,
              ),
            ),
          ),

          // ── Loading State ───────────────────────────────────────
          if (isLoading) ...[
            SliverToBoxAdapter(child: _FeaturedBannerSkeleton()),
            SliverToBoxAdapter(child: _HorizontalCardSkeletons()),
            SliverToBoxAdapter(child: _TrendingGridSkeleton()),
            SliverToBoxAdapter(child: _WideCardSkeletons()),
          ],

          // ── Loaded Content ──────────────────────────────────────
          if (!isLoading) ...[
            // 2. Featured Banner
            if (feed.featured.isNotEmpty)
              SliverToBoxAdapter(
                child: SlideTransition(
                  position: _bannerSlide,
                  child: FadeTransition(
                    opacity: _bannerFade,
                    child: _FeaturedBanner(listings: feed.featured),
                  ),
                ),
              ),

            // 3. Live Now
            if (feed.liveNow.isNotEmpty)
              SliverToBoxAdapter(
                child: _LiveNowBanner(listings: feed.liveNow),
              ),

            // 4. Ending Soon
            if (feed.endingSoon.isNotEmpty) ...[
              SliverToBoxAdapter(
                child: _SectionHeader(
                  titleAr: 'ينتهي قريباً',
                  titleEn: 'Ending soon',
                  count: feed.endingSoon.length,
                  onSeeAll: () => context.push(AppRoutes.search),
                ),
              ),
              SliverToBoxAdapter(
                child: _EndingSoonRow(listings: feed.endingSoon),
              ),
            ],

            // 5. Trending
            if (feed.trending.isNotEmpty) ...[
              SliverToBoxAdapter(
                child: _SectionHeader(
                  titleAr: 'الأكثر مزايدة',
                  titleEn: 'Trending',
                  icon: Icons.local_fire_department_rounded,
                  iconColor: AppColors.ember,
                  onSeeAll: () => context.push(AppRoutes.search),
                ),
              ),
              SliverPadding(
                padding: const EdgeInsetsDirectional.symmetric(horizontal: AppSpacing.md),
                sliver: SliverGrid(
                  gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                    crossAxisCount: 2,
                    childAspectRatio: 0.72,
                    mainAxisSpacing: AppSpacing.sm,
                    crossAxisSpacing: AppSpacing.sm,
                  ),
                  delegate: SliverChildBuilderDelegate(
                    (context, index) {
                      final listing = feed.trending[index];
                      return _StaggeredGridItem(
                        index: index,
                        child: ListingCard(
                          listing: listing,
                          onTap: () => context.push('/listing/${listing.id}'),
                        ),
                      );
                    },
                    childCount: math.min(feed.trending.length, 6),
                  ),
                ),
              ),
            ],

            // 6. New Listings
            if (feed.newListings.isNotEmpty) ...[
              SliverToBoxAdapter(
                child: _SectionHeader(
                  titleAr: 'جديد',
                  titleEn: 'New listings',
                ),
              ),
              SliverPadding(
                padding: const EdgeInsetsDirectional.symmetric(horizontal: AppSpacing.md),
                sliver: SliverList(
                  delegate: SliverChildBuilderDelegate(
                    (context, index) {
                      final listing = feed.newListings[index];
                      return _WideListingCard(
                        listing: listing,
                        index: index,
                      );
                    },
                    childCount: feed.newListings.length,
                  ),
                ),
              ),
            ],

            // 7. Sell CTA
            const SliverToBoxAdapter(child: _SellCTA()),
          ],

          // Bottom safe-area padding for nav bar
          const SliverToBoxAdapter(child: SizedBox(height: 100)),
        ],
      ),
    );
  }

  bool _hasNoData(HomeFeedState feed) =>
      feed.featured.isEmpty &&
      feed.endingSoon.isEmpty &&
      feed.trending.isEmpty &&
      feed.newListings.isEmpty;
}

// ═══════════════════════════════════════════════════════════════════
//  §0  App Bar
// ═══════════════════════════════════════════════════════════════════

class _MzadakAppBar extends ConsumerStatefulWidget {
  const _MzadakAppBar({required this.searchHintIndex});
  final int searchHintIndex;

  @override
  ConsumerState<_MzadakAppBar> createState() => _MzadakAppBarState();
}

class _MzadakAppBarState extends ConsumerState<_MzadakAppBar> {
  @override
  void initState() {
    super.initState();
    Future.microtask(() {
      ref.read(notificationProvider.notifier).loadNotifications();
    });
  }

  String _greeting() {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'صباح الخير';
    if (hour < 17) return 'مساء الخير';
    return 'مساء الخير';
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final notif = ref.watch(notificationProvider);
    final name = auth.fullNameAr;
    final greetText = name != null ? '${_greeting()}، $name' : 'مرحباً بك في مزادك';

    return SliverAppBar(
      pinned: true,
      floating: false,
      expandedHeight: 130,
      backgroundColor: AppColors.navy,
      surfaceTintColor: Colors.transparent,
      flexibleSpace: FlexibleSpaceBar(
        background: SafeArea(
          child: Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(16, 8, 16, 0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // ── Top row: avatar + logo + bell ────────────────
                Row(
                  children: [
                    // Avatar
                    GestureDetector(
                      onTap: () => context.push(AppRoutes.profile),
                      child: Container(
                        width: 36,
                        height: 36,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          border: Border.all(color: AppColors.gold, width: 1.5),
                          color: AppColors.navy,
                        ),
                        child: const Center(
                          child: Text('م', style: TextStyle(
                            color: AppColors.gold, fontSize: 16, fontWeight: FontWeight.w700,
                          )),
                        ),
                      ),
                    ),
                    const Spacer(),

                    // Logo
                    Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          'مزادك',
                          style: TextStyle(
                            color: AppColors.gold,
                            fontSize: 20,
                            fontWeight: FontWeight.w800,
                            letterSpacing: -0.5,
                          ),
                        ),
                        const Text(
                          'M Z A D A K',
                          style: TextStyle(
                            color: Colors.white54,
                            fontSize: 8,
                            fontWeight: FontWeight.w600,
                            letterSpacing: 3,
                          ),
                        ),
                      ],
                    ),

                    const Spacer(),

                    // Notification bell
                    GestureDetector(
                      onTap: () => context.push(AppRoutes.notifications),
                      child: Stack(
                        clipBehavior: Clip.none,
                        children: [
                          const Icon(Icons.notifications_outlined, color: Colors.white, size: 26),
                          if (notif.unreadCount > 0)
                            PositionedDirectional(
                              top: -4,
                              end: -4,
                              child: Container(
                                padding: const EdgeInsets.all(3),
                                decoration: const BoxDecoration(
                                  color: AppColors.ember,
                                  shape: BoxShape.circle,
                                ),
                                child: Text(
                                  notif.unreadCount > 9 ? '9+' : '${notif.unreadCount}',
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontSize: 9,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                ),

                const SizedBox(height: 6),

                // ── Greeting ─────────────────────────────────────
                Text(
                  greetText,
                  style: const TextStyle(
                    color: Colors.white70,
                    fontSize: 12,
                    fontWeight: FontWeight.w500,
                  ),
                  textAlign: TextAlign.center,
                ),

                const SizedBox(height: 10),

                // ── Search Bar ───────────────────────────────────
                GestureDetector(
                  onTap: () => context.push(AppRoutes.search),
                  child: Hero(
                    tag: 'search-bar',
                    child: Material(
                      color: Colors.transparent,
                      child: Container(
                        height: 42,
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.12),
                          borderRadius: AppSpacing.radiusFull,
                          border: Border.all(color: Colors.white24, width: 0.5),
                        ),
                        padding: const EdgeInsetsDirectional.symmetric(horizontal: 16),
                        child: Row(
                          children: [
                            const Icon(Icons.search_rounded, color: Colors.white54, size: 20),
                            const SizedBox(width: 10),
                            Expanded(
                              child: AnimatedSwitcher(
                                duration: const Duration(milliseconds: 400),
                                transitionBuilder: (child, anim) => FadeTransition(
                                  opacity: anim,
                                  child: SlideTransition(
                                    position: Tween<Offset>(
                                      begin: const Offset(0, 0.3),
                                      end: Offset.zero,
                                    ).animate(anim),
                                    child: child,
                                  ),
                                ),
                                child: Text(
                                  'ابحث... ${_searchHints[widget.searchHintIndex]}',
                                  key: ValueKey(widget.searchHintIndex),
                                  style: const TextStyle(
                                    color: Colors.white38,
                                    fontSize: 13,
                                    fontWeight: FontWeight.w400,
                                  ),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ),
                            Container(
                              width: 1,
                              height: 20,
                              color: Colors.white12,
                            ),
                            const SizedBox(width: 10),
                            const Icon(Icons.tune_rounded, color: Colors.white54, size: 18),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §1  Category Pills
// ═══════════════════════════════════════════════════════════════════

class _CategoryRow extends StatelessWidget {
  const _CategoryRow({required this.selected, required this.onTap});
  final int selected;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 56,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsetsDirectional.fromSTEB(16, 10, 16, 10),
        itemCount: _categories.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, index) {
          final cat = _categories[index];
          final isActive = index == selected;
          return GestureDetector(
            onTap: () => onTap(index),
            child: AnimatedContainer(
              duration: AppAnimations.state,
              curve: Curves.easeOut,
              padding: const EdgeInsetsDirectional.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                color: isActive ? AppColors.gold : Colors.white,
                borderRadius: AppSpacing.radiusFull,
                border: Border.all(
                  color: isActive ? AppColors.gold : AppColors.sand,
                  width: 1,
                ),
                boxShadow: isActive
                    ? [BoxShadow(color: AppColors.gold.withValues(alpha: 0.25), blurRadius: 8, offset: const Offset(0, 2))]
                    : null,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    cat.icon,
                    size: 16,
                    color: isActive ? Colors.white : AppColors.navy,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    cat.labelAr,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: isActive ? Colors.white : AppColors.navy,
                    ),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §2  Featured Banner (PageView carousel)
// ═══════════════════════════════════════════════════════════════════

class _FeaturedBanner extends StatefulWidget {
  const _FeaturedBanner({required this.listings});
  final List<ListingSummary> listings;

  @override
  State<_FeaturedBanner> createState() => _FeaturedBannerState();
}

class _FeaturedBannerState extends State<_FeaturedBanner> {
  late final PageController _pageCtrl;
  int _currentPage = 0;
  Timer? _autoAdvance;

  @override
  void initState() {
    super.initState();
    _pageCtrl = PageController(viewportFraction: 0.92);
    if (widget.listings.length > 1) {
      _autoAdvance = Timer.periodic(
        const Duration(milliseconds: _kBannerAutoAdvanceMs),
        (_) {
          if (!mounted) return;
          final next = (_currentPage + 1) % widget.listings.length;
          _pageCtrl.animateToPage(
            next,
            duration: AppAnimations.enter,
            curve: AppAnimations.enterCurve,
          );
        },
      );
    }
  }

  @override
  void dispose() {
    _autoAdvance?.cancel();
    _pageCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        SizedBox(
          height: _kBannerHeight,
          child: PageView.builder(
            controller: _pageCtrl,
            itemCount: widget.listings.length,
            onPageChanged: (i) => setState(() => _currentPage = i),
            itemBuilder: (context, index) {
              final listing = widget.listings[index];
              return GestureDetector(
                onTap: () => context.push('/listing/${listing.id}'),
                child: Container(
                  margin: const EdgeInsetsDirectional.symmetric(horizontal: 4, vertical: 8),
                  decoration: BoxDecoration(
                    borderRadius: AppSpacing.radiusLg,
                    boxShadow: [
                      BoxShadow(
                        color: AppColors.navy.withValues(alpha: 0.18),
                        blurRadius: 16,
                        offset: const Offset(0, 6),
                      ),
                    ],
                  ),
                  child: ClipRRect(
                    borderRadius: AppSpacing.radiusLg,
                    child: Stack(
                      fit: StackFit.expand,
                      children: [
                        // Background image
                        CachedNetworkImage(
                          imageUrl: listing.imageUrl,
                          fit: BoxFit.cover,
                          placeholder: (_, __) => Container(color: AppColors.sand),
                          errorWidget: (_, __, ___) => Container(
                            color: AppColors.navy,
                            child: const Icon(Icons.gavel_rounded, color: AppColors.gold, size: 48),
                          ),
                        ),

                        // Gradient overlay
                        Container(
                          decoration: BoxDecoration(
                            gradient: LinearGradient(
                              begin: Alignment.topCenter,
                              end: Alignment.bottomCenter,
                              colors: [
                                Colors.transparent,
                                AppColors.navy.withValues(alpha: 0.45),
                                AppColors.navy.withValues(alpha: 0.88),
                              ],
                              stops: const [0.25, 0.6, 1.0],
                            ),
                          ),
                        ),

                        // Content
                        Positioned(
                          bottom: 16,
                          left: 16,
                          right: 16,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              // Badges row
                              Row(
                                children: [
                                  if (listing.isCertified)
                                    _Badge(label: 'CERTIFIED', color: AppColors.emerald),
                                  if (listing.isCertified) const SizedBox(width: 6),
                                  if (listing.isLive)
                                    _Badge(label: 'LIVE', color: AppColors.ember),
                                ],
                              ),
                              const SizedBox(height: 8),

                              // Title
                              Text(
                                listing.titleAr,
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 17,
                                  fontWeight: FontWeight.w700,
                                  height: 1.2,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              if (listing.titleEn != null) ...[
                                const SizedBox(height: 2),
                                Text(
                                  listing.titleEn!,
                                  style: TextStyle(
                                    color: Colors.white.withValues(alpha: 0.7),
                                    fontSize: 12,
                                    fontWeight: FontWeight.w500,
                                  ),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ],

                              const SizedBox(height: 10),

                              // Price + Bid button
                              Row(
                                children: [
                                  Text(
                                    ArabicNumerals.formatCurrency(listing.displayPrice, listing.currency),
                                    style: const TextStyle(
                                      color: AppColors.gold,
                                      fontSize: 20,
                                      fontWeight: FontWeight.w800,
                                      fontFamily: 'Sora',
                                    ),
                                  ),
                                  const Spacer(),
                                  Container(
                                    padding: const EdgeInsetsDirectional.symmetric(horizontal: 16, vertical: 8),
                                    decoration: BoxDecoration(
                                      color: AppColors.gold,
                                      borderRadius: AppSpacing.radiusFull,
                                    ),
                                    child: const Text(
                                      'زايد الآن',
                                      style: TextStyle(
                                        color: Colors.white,
                                        fontSize: 12,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            },
          ),
        ),

        // Page indicator dots
        if (widget.listings.length > 1)
          Padding(
            padding: const EdgeInsets.only(top: 4, bottom: 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(widget.listings.length, (i) {
                final isActive = i == _currentPage;
                return AnimatedContainer(
                  duration: AppAnimations.state,
                  margin: const EdgeInsets.symmetric(horizontal: 3),
                  width: isActive ? 20 : 6,
                  height: 6,
                  decoration: BoxDecoration(
                    color: isActive ? AppColors.gold : AppColors.sand,
                    borderRadius: AppSpacing.radiusFull,
                  ),
                );
              }),
            ),
          ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §3  Live Now Banner
// ═══════════════════════════════════════════════════════════════════

class _LiveNowBanner extends StatefulWidget {
  const _LiveNowBanner({required this.listings});
  final List<ListingSummary> listings;

  @override
  State<_LiveNowBanner> createState() => _LiveNowBannerState();
}

class _LiveNowBannerState extends State<_LiveNowBanner>
    with SingleTickerProviderStateMixin {
  int _currentIndex = 0;
  Timer? _rotateTimer;
  late final AnimationController _pulseCtrl;
  late final Animation<double> _pulseOpacity;

  @override
  void initState() {
    super.initState();
    _pulseCtrl = AnimationController(vsync: this, duration: const Duration(seconds: 1));
    _pulseOpacity = Tween<double>(begin: 1.0, end: 0.3).animate(
      CurvedAnimation(parent: _pulseCtrl, curve: Curves.easeInOut),
    );
    _pulseCtrl.repeat(reverse: true);

    if (widget.listings.length > 1) {
      _rotateTimer = Timer.periodic(
        const Duration(milliseconds: _kLiveRotateMs),
        (_) {
          if (mounted) {
            setState(() => _currentIndex = (_currentIndex + 1) % widget.listings.length);
            HapticFeedback.selectionClick();
          }
        },
      );
    }
  }

  @override
  void dispose() {
    _rotateTimer?.cancel();
    _pulseCtrl.dispose();
    super.dispose();
  }

  String _formatTimeLeft(String? endsAt) {
    if (endsAt == null) return '';
    final diff = DateTime.parse(endsAt).difference(DateTime.now().toUtc());
    if (diff.isNegative) return 'انتهى';
    if (diff.inHours > 0) return '${diff.inHours}h ${diff.inMinutes.remainder(60)}m left';
    return '${diff.inMinutes}:${(diff.inSeconds.remainder(60)).toString().padLeft(2, '0')} left';
  }

  @override
  Widget build(BuildContext context) {
    final listing = widget.listings[_currentIndex];
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(16, 4, 16, AppSpacing.sm),
      child: GestureDetector(
        onTap: () => context.push('/auction/${listing.id}'),
        child: Container(
          decoration: BoxDecoration(
            borderRadius: AppSpacing.radiusMd,
            gradient: const LinearGradient(
              colors: [Color(0xFF152840), AppColors.navy],
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
            ),
            border: Border.all(
              color: AppColors.ember.withValues(alpha: 0.5),
              width: 1.5,
            ),
          ),
          padding: const EdgeInsetsDirectional.all(14),
          child: AnimatedSwitcher(
            duration: AppAnimations.enter,
            child: Row(
              key: ValueKey(listing.id),
              children: [
                // Live indicator
                Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    AnimatedBuilder(
                      animation: _pulseOpacity,
                      builder: (_, child) => Opacity(
                        opacity: _pulseOpacity.value,
                        child: child,
                      ),
                      child: Container(
                        width: 10,
                        height: 10,
                        decoration: const BoxDecoration(
                          color: AppColors.ember,
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      'LIVE',
                      style: TextStyle(
                        color: AppColors.ember,
                        fontSize: 8,
                        fontWeight: FontWeight.w800,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
                const SizedBox(width: 14),

                // Info
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        listing.titleAr,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Text(
                            '${listing.bidCount} مزايد يشاهد الآن',
                            style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.6),
                              fontSize: 11,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            _formatTimeLeft(listing.endsAt),
                            style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.5),
                              fontSize: 11,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),

                // Price
                Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      ArabicNumerals.formatCurrency(listing.displayPrice, listing.currency),
                      style: const TextStyle(
                        color: AppColors.gold,
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                        fontFamily: 'Sora',
                      ),
                    ),
                    const SizedBox(height: 4),
                    Container(
                      padding: const EdgeInsetsDirectional.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: AppColors.ember,
                        borderRadius: AppSpacing.radiusFull,
                      ),
                      child: const Text(
                        'انضم',
                        style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §4  Ending Soon — Horizontal Scroll
// ═══════════════════════════════════════════════════════════════════

class _EndingSoonRow extends StatefulWidget {
  const _EndingSoonRow({required this.listings});
  final List<ListingSummary> listings;

  @override
  State<_EndingSoonRow> createState() => _EndingSoonRowState();
}

class _EndingSoonRowState extends State<_EndingSoonRow>
    with TickerProviderStateMixin {
  final List<AnimationController> _ctrls = [];
  final List<Animation<double>> _fades = [];
  final List<Animation<Offset>> _slides = [];

  @override
  void initState() {
    super.initState();
    for (var i = 0; i < widget.listings.length; i++) {
      final ctrl = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 350),
      );
      _ctrls.add(ctrl);
      _fades.add(CurvedAnimation(parent: ctrl, curve: Curves.easeOut));
      _slides.add(Tween<Offset>(
        begin: const Offset(0, 0.1),
        end: Offset.zero,
      ).animate(CurvedAnimation(parent: ctrl, curve: AppAnimations.enterCurve)));

      Future.delayed(Duration(milliseconds: 300 + i * _kStaggerDelayMs), () {
        if (mounted) ctrl.forward();
      });
    }
  }

  @override
  void dispose() {
    for (final c in _ctrls) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: _kCompactCardHeight,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsetsDirectional.symmetric(horizontal: AppSpacing.md),
        itemCount: widget.listings.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
        itemBuilder: (context, index) {
          if (index >= _ctrls.length) return const SizedBox.shrink();
          return FadeTransition(
            opacity: _fades[index],
            child: SlideTransition(
              position: _slides[index],
              child: _CompactListingCard(listing: widget.listings[index]),
            ),
          );
        },
      ),
    );
  }
}

class _CompactListingCard extends StatelessWidget {
  const _CompactListingCard({required this.listing});
  final ListingSummary listing;

  @override
  Widget build(BuildContext context) {
    final isUrgent = _isUrgent(listing.endsAt);

    return GestureDetector(
      onTap: () => context.push('/listing/${listing.id}'),
      child: Container(
        width: _kCompactCardWidth,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(color: AppColors.sand, width: 1),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.05),
              blurRadius: 8,
              offset: const Offset(0, 2),
            ),
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Image section
            ClipRRect(
              borderRadius: const BorderRadius.vertical(top: Radius.circular(11)),
              child: SizedBox(
                height: 100,
                width: double.infinity,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    CachedNetworkImage(
                      imageUrl: listing.imageUrl,
                      fit: BoxFit.cover,
                      placeholder: (_, __) => Container(color: AppColors.sand),
                      errorWidget: (_, __, ___) => Container(
                        color: AppColors.sand,
                        child: const Icon(Icons.image_rounded, color: AppColors.mist, size: 24),
                      ),
                    ),
                    // Bottom scrim
                    Positioned(
                      bottom: 0,
                      left: 0,
                      right: 0,
                      height: 30,
                      child: Container(
                        decoration: BoxDecoration(
                          gradient: LinearGradient(
                            begin: Alignment.topCenter,
                            end: Alignment.bottomCenter,
                            colors: [Colors.transparent, Colors.black.withValues(alpha: 0.3)],
                          ),
                        ),
                      ),
                    ),
                    // Timer badge
                    PositionedDirectional(
                      top: 6,
                      end: 6,
                      child: _TimerBadge(
                        endsAt: listing.endsAt,
                        isUrgent: isUrgent,
                      ),
                    ),
                    // Badges
                    if (listing.isCertified)
                      const PositionedDirectional(
                        top: 6,
                        start: 6,
                        child: _Badge(label: 'CERTIFIED', color: AppColors.emerald),
                      ),
                    if (listing.isLive && !listing.isCertified)
                      const PositionedDirectional(
                        top: 6,
                        start: 6,
                        child: _Badge(label: 'LIVE', color: AppColors.ember),
                      ),
                    // Condition badge (frosted glass)
                    PositionedDirectional(
                      bottom: 6,
                      start: 6,
                      child: Container(
                        padding: const EdgeInsetsDirectional.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.85),
                          borderRadius: AppSpacing.radiusSm,
                        ),
                        child: Text(
                          listing.condition,
                          style: const TextStyle(
                            fontSize: 9,
                            fontWeight: FontWeight.w600,
                            color: AppColors.navy,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),

            // Info section
            Expanded(
              child: Padding(
                padding: const EdgeInsetsDirectional.all(8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Price
                    Text(
                      ArabicNumerals.formatCurrency(listing.displayPrice, listing.currency),
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w800,
                        color: AppColors.navy,
                        fontFamily: 'Sora',
                      ),
                      maxLines: 1,
                    ),
                    const SizedBox(height: 3),
                    // Title
                    Text(
                      listing.titleAr,
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: AppColors.ink,
                        height: 1.2,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const Spacer(),
                    // Bid count + Bid button
                    Row(
                      children: [
                        Icon(Icons.gavel_rounded, size: 11, color: AppColors.mist),
                        const SizedBox(width: 3),
                        Text(
                          '${listing.bidCount} مزايدة',
                          style: const TextStyle(fontSize: 10, color: AppColors.mist),
                        ),
                        const Spacer(),
                        Container(
                          padding: const EdgeInsetsDirectional.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: AppColors.navy,
                            borderRadius: AppSpacing.radiusFull,
                          ),
                          child: const Text(
                            'Bid',
                            style: TextStyle(
                              color: Colors.white,
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),

            // Time progress bar
            ClipRRect(
              borderRadius: const BorderRadius.vertical(bottom: Radius.circular(11)),
              child: _TimeProgressBar(endsAt: listing.endsAt),
            ),
          ],
        ),
      ),
    );
  }

  bool _isUrgent(String? endsAt) {
    if (endsAt == null) return false;
    final diff = DateTime.parse(endsAt).difference(DateTime.now().toUtc());
    return diff.inMinutes < 5 && !diff.isNegative;
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §5  Trending Grid — Staggered Item
// ═══════════════════════════════════════════════════════════════════

class _StaggeredGridItem extends StatefulWidget {
  const _StaggeredGridItem({required this.index, required this.child});
  final int index;
  final Widget child;

  @override
  State<_StaggeredGridItem> createState() => _StaggeredGridItemState();
}

class _StaggeredGridItemState extends State<_StaggeredGridItem>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _fade;
  late final Animation<Offset> _slide;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 350));
    _fade = CurvedAnimation(parent: _ctrl, curve: Curves.easeOut);
    _slide = Tween<Offset>(begin: const Offset(0, 0.06), end: Offset.zero)
        .animate(CurvedAnimation(parent: _ctrl, curve: AppAnimations.enterCurve));

    Future.delayed(Duration(milliseconds: widget.index * _kStaggerDelayMs), () {
      if (mounted) _ctrl.forward();
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _fade,
      child: SlideTransition(
        position: _slide,
        child: widget.child,
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §6  New Listings — Wide Card
// ═══════════════════════════════════════════════════════════════════

class _WideListingCard extends StatefulWidget {
  const _WideListingCard({required this.listing, required this.index});
  final ListingSummary listing;
  final int index;

  @override
  State<_WideListingCard> createState() => _WideListingCardState();
}

class _WideListingCardState extends State<_WideListingCard>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;
  late final Animation<double> _fade;
  late final Animation<Offset> _slide;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 350));
    _fade = CurvedAnimation(parent: _ctrl, curve: Curves.easeOut);
    _slide = Tween<Offset>(begin: const Offset(0, 0.05), end: Offset.zero)
        .animate(CurvedAnimation(parent: _ctrl, curve: AppAnimations.enterCurve));

    Future.delayed(Duration(milliseconds: widget.index * _kStaggerDelayMs), () {
      if (mounted) _ctrl.forward();
    });
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final listing = widget.listing;
    return FadeTransition(
      opacity: _fade,
      child: SlideTransition(
        position: _slide,
        child: GestureDetector(
          onTap: () => context.push('/listing/${listing.id}'),
          child: Container(
            margin: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
            padding: const EdgeInsetsDirectional.all(12),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: AppSpacing.radiusMd,
              border: Border.all(color: AppColors.sand, width: 1),
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.04),
                  blurRadius: 8,
                  offset: const Offset(0, 2),
                ),
              ],
            ),
            child: Row(
              children: [
                // Thumbnail
                Hero(
                  tag: HeroTags.listingImage(listing.id),
                  child: ClipRRect(
                    borderRadius: AppSpacing.radiusMd,
                    child: SizedBox(
                      width: _kWideThumbSize,
                      height: _kWideThumbSize,
                      child: CachedNetworkImage(
                        imageUrl: listing.imageUrl,
                        fit: BoxFit.cover,
                        placeholder: (_, __) => Container(color: AppColors.sand),
                        errorWidget: (_, __, ___) => Container(
                          color: AppColors.sand,
                          child: const Icon(Icons.image_rounded, color: AppColors.mist, size: 24),
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 14),

                // Info
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Title EN
                      if (listing.titleEn != null)
                        Text(
                          listing.titleEn!,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: AppColors.ink,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      // Title AR
                      Text(
                        listing.titleAr,
                        style: TextStyle(
                          fontSize: listing.titleEn != null ? 11 : 14,
                          fontWeight: listing.titleEn != null ? FontWeight.w500 : FontWeight.w700,
                          color: listing.titleEn != null ? AppColors.mist : AppColors.ink,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 6),

                      // Price
                      Text(
                        ArabicNumerals.formatCurrency(listing.displayPrice, listing.currency),
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: AppColors.navy,
                          fontFamily: 'Sora',
                        ),
                      ),
                      const SizedBox(height: 6),

                      // Bottom row
                      Row(
                        children: [
                          // Time left
                          Icon(Icons.schedule_rounded, size: 13, color: AppColors.mist),
                          const SizedBox(width: 3),
                          Text(
                            _formatTimeLeft(listing.endsAt),
                            style: const TextStyle(fontSize: 11, color: AppColors.mist),
                          ),
                          const SizedBox(width: 10),
                          // Bids
                          Icon(Icons.gavel_rounded, size: 13, color: AppColors.mist),
                          const SizedBox(width: 3),
                          Text(
                            'bids ${listing.bidCount}',
                            style: const TextStyle(fontSize: 11, color: AppColors.mist),
                          ),
                          const Spacer(),
                          // Bid button
                          Container(
                            padding: const EdgeInsetsDirectional.symmetric(horizontal: 14, vertical: 6),
                            decoration: BoxDecoration(
                              color: AppColors.navy,
                              borderRadius: AppSpacing.radiusFull,
                            ),
                            child: const Text(
                              'زايد',
                              style: TextStyle(
                                color: Colors.white,
                                fontSize: 11,
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),

                // Condition badge
                const SizedBox(width: 8),
                _ConditionBadge(condition: listing.condition),
              ],
            ),
          ),
        ),
      ),
    );
  }

  static String _formatTimeLeft(String? endsAt) {
    if (endsAt == null) return '';
    final diff = DateTime.parse(endsAt).difference(DateTime.now().toUtc());
    if (diff.isNegative) return 'انتهى';
    if (diff.inDays > 0) return '${diff.inDays}d ${diff.inHours.remainder(24)}h';
    if (diff.inHours > 0) return '${diff.inHours}h ${diff.inMinutes.remainder(60)}m';
    return '${diff.inMinutes}m';
  }
}

// ═══════════════════════════════════════════════════════════════════
//  §7  Sell CTA
// ═══════════════════════════════════════════════════════════════════

class _SellCTA extends StatelessWidget {
  const _SellCTA();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(
        AppSpacing.md, AppSpacing.sectionGap, AppSpacing.md, 0,
      ),
      child: GestureDetector(
        onTap: () => context.push(AppRoutes.snapToList),
        child: Container(
          height: 72,
          decoration: BoxDecoration(
            color: AppColors.cream,
            borderRadius: AppSpacing.radiusLg,
            border: Border.all(color: AppColors.gold, width: 1),
          ),
          padding: const EdgeInsetsDirectional.symmetric(horizontal: 20),
          child: Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: AppColors.navy,
                  borderRadius: AppSpacing.radiusMd,
                ),
                child: const Icon(Icons.camera_alt_rounded, color: AppColors.gold, size: 20),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: const [
                    Text(
                      'اعرض سلعتك في ٦٠ ثانية',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                      ),
                    ),
                    Text(
                      'List your item in 60 seconds',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: AppColors.mist,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.arrow_forward_ios_rounded, color: AppColors.gold, size: 16),
            ],
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Shared Widgets
// ═══════════════════════════════════════════════════════════════════

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({
    required this.titleAr,
    required this.titleEn,
    this.count,
    this.onSeeAll,
    this.icon,
    this.iconColor,
  });

  final String titleAr;
  final String titleEn;
  final int? count;
  final VoidCallback? onSeeAll;
  final IconData? icon;
  final Color? iconColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(
        AppSpacing.md, AppSpacing.sectionGap, AppSpacing.md, AppSpacing.sm,
      ),
      child: Row(
        children: [
          if (icon != null) ...[
            Icon(icon, size: 18, color: iconColor ?? AppColors.navy),
            const SizedBox(width: 6),
          ],
          Text(
            '$titleEn · $titleAr',
            style: const TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.navy,
            ),
          ),
          if (count != null) ...[
            const SizedBox(width: 6),
            Container(
              padding: const EdgeInsetsDirectional.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                color: AppColors.sand,
                borderRadius: AppSpacing.radiusFull,
              ),
              child: Text(
                '$count',
                style: const TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
            ),
          ],
          const Spacer(),
          if (onSeeAll != null)
            GestureDetector(
              onTap: onSeeAll,
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Text(
                    'See all',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: AppColors.gold,
                    ),
                  ),
                  SizedBox(width: 2),
                  Icon(Icons.arrow_forward_ios_rounded, size: 12, color: AppColors.gold),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color,
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 8,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

class _ConditionBadge extends StatelessWidget {
  const _ConditionBadge({required this.condition});
  final String condition;

  @override
  Widget build(BuildContext context) {
    return RotatedBox(
      quarterTurns: 1,
      child: Container(
        padding: const EdgeInsetsDirectional.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: AppColors.cream,
          borderRadius: AppSpacing.radiusSm,
          border: Border.all(color: AppColors.sand, width: 0.5),
        ),
        child: Text(
          condition,
          style: const TextStyle(
            fontSize: 9,
            fontWeight: FontWeight.w600,
            color: AppColors.gold,
          ),
        ),
      ),
    );
  }
}

class _TimerBadge extends StatelessWidget {
  const _TimerBadge({required this.endsAt, this.isUrgent = false});
  final String? endsAt;
  final bool isUrgent;

  @override
  Widget build(BuildContext context) {
    if (endsAt == null) return const SizedBox.shrink();
    final diff = DateTime.parse(endsAt!).difference(DateTime.now().toUtc());
    if (diff.isNegative) return const SizedBox.shrink();

    String text;
    if (diff.inHours > 0) {
      text = '${diff.inHours}:${diff.inMinutes.remainder(60).toString().padLeft(2, '0')}';
    } else {
      text = '${diff.inMinutes}:${diff.inSeconds.remainder(60).toString().padLeft(2, '0')}';
    }

    return Container(
      padding: const EdgeInsetsDirectional.symmetric(horizontal: 6, vertical: 3),
      decoration: BoxDecoration(
        color: isUrgent ? AppColors.ember : AppColors.navy.withValues(alpha: 0.85),
        borderRadius: AppSpacing.radiusSm,
        boxShadow: isUrgent
            ? [BoxShadow(color: AppColors.ember.withValues(alpha: 0.5), blurRadius: 8)]
            : null,
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: Colors.white,
          fontSize: 10,
          fontWeight: FontWeight.w700,
          fontFamily: 'Sora',
          letterSpacing: 0.3,
        ),
      ),
    );
  }
}

class _TimeProgressBar extends StatelessWidget {
  const _TimeProgressBar({required this.endsAt});
  final String? endsAt;

  @override
  Widget build(BuildContext context) {
    if (endsAt == null) return const SizedBox(height: 3);

    final end = DateTime.parse(endsAt!);
    final now = DateTime.now().toUtc();
    final total = end.difference(end.subtract(const Duration(days: 7)));
    final remaining = end.difference(now);
    final progress = (1.0 - (remaining.inSeconds / total.inSeconds)).clamp(0.0, 1.0);

    return SizedBox(
      height: 3,
      child: LinearProgressIndicator(
        value: progress,
        backgroundColor: AppColors.sand,
        valueColor: AlwaysStoppedAnimation(
          progress > 0.8 ? AppColors.ember : AppColors.emerald,
        ),
        minHeight: 3,
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
//  Skeleton Loading States
// ═══════════════════════════════════════════════════════════════════

class _FeaturedBannerSkeleton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(16, 8, 16, 8),
      child: Shimmer.fromColors(
        baseColor: AppColors.sand,
        highlightColor: AppColors.cream,
        child: Container(
          height: _kBannerHeight - 20,
          decoration: BoxDecoration(
            color: AppColors.sand,
            borderRadius: AppSpacing.radiusLg,
          ),
        ),
      ),
    );
  }
}

class _HorizontalCardSkeletons extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Section header skeleton
        Padding(
          padding: const EdgeInsetsDirectional.fromSTEB(16, AppSpacing.sectionGap, 16, AppSpacing.sm),
          child: Shimmer.fromColors(
            baseColor: AppColors.sand,
            highlightColor: AppColors.cream,
            child: Container(
              width: 180,
              height: 16,
              decoration: BoxDecoration(
                color: AppColors.sand,
                borderRadius: AppSpacing.radiusSm,
              ),
            ),
          ),
        ),
        SizedBox(
          height: _kCompactCardHeight,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            physics: const NeverScrollableScrollPhysics(),
            padding: const EdgeInsetsDirectional.symmetric(horizontal: AppSpacing.md),
            itemCount: 4,
            separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
            itemBuilder: (_, __) => Shimmer.fromColors(
              baseColor: AppColors.sand,
              highlightColor: AppColors.cream,
              child: Container(
                width: _kCompactCardWidth,
                decoration: BoxDecoration(
                  color: AppColors.sand,
                  borderRadius: AppSpacing.radiusMd,
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _TrendingGridSkeleton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(16, AppSpacing.sectionGap, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header skeleton
          Shimmer.fromColors(
            baseColor: AppColors.sand,
            highlightColor: AppColors.cream,
            child: Container(
              width: 160,
              height: 16,
              decoration: BoxDecoration(color: AppColors.sand, borderRadius: AppSpacing.radiusSm),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          // Grid
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              childAspectRatio: 0.72,
              mainAxisSpacing: AppSpacing.sm,
              crossAxisSpacing: AppSpacing.sm,
            ),
            itemCount: 4,
            itemBuilder: (_, __) => const ListingCardSkeleton(),
          ),
        ],
      ),
    );
  }
}

class _WideCardSkeletons extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(16, AppSpacing.sectionGap, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Shimmer.fromColors(
            baseColor: AppColors.sand,
            highlightColor: AppColors.cream,
            child: Container(
              width: 130,
              height: 16,
              decoration: BoxDecoration(color: AppColors.sand, borderRadius: AppSpacing.radiusSm),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          // Cards
          ...List.generate(3, (_) => Padding(
            padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
            child: Shimmer.fromColors(
              baseColor: AppColors.sand,
              highlightColor: AppColors.cream,
              child: Container(
                height: _kWideThumbSize + 24,
                decoration: BoxDecoration(
                  color: AppColors.sand,
                  borderRadius: AppSpacing.radiusMd,
                ),
              ),
            ),
          )),
        ],
      ),
    );
  }
}
