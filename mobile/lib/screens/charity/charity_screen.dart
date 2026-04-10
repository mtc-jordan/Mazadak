import 'dart:math' as math;

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/core_providers.dart';
import '../../core/providers/listings_provider.dart';
import '../../core/router.dart';
import '../../core/theme/animations.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import '../../widgets/listing_card.dart';
import '../../widgets/mzadak_refresh_indicator.dart';

// ═══════════════════════════════════════════════════════════════
// Charity Color Tokens
// ═══════════════════════════════════════════════════════════════

const _teal = Color(0xFF0F6E56);
const _tealLight = Color(0xFF0D8A72);
const _tealDark = Color(0xFF0A5A46);
const _tealSurface = Color(0xFFE8F5F1);

// ═══════════════════════════════════════════════════════════════
// Provider
// ═══════════════════════════════════════════════════════════════

class CharityState {
  const CharityState({
    this.listings = const [],
    this.isLoading = false,
    this.error,
    this.page = 1,
    this.hasMore = true,
    this.totalRaised = 0,
    this.auctionCount = 0,
    this.ngoCount = 0,
    this.campaignGoal = 10000,
  });

  final List<ListingSummary> listings;
  final bool isLoading;
  final String? error;
  final int page;
  final bool hasMore;
  final double totalRaised;
  final int auctionCount;
  final int ngoCount;
  final double campaignGoal;

  double get progress =>
      campaignGoal > 0 ? (totalRaised / campaignGoal).clamp(0.0, 1.0) : 0;

  CharityState copyWith({
    List<ListingSummary>? listings,
    bool? isLoading,
    String? error,
    int? page,
    bool? hasMore,
    double? totalRaised,
    int? auctionCount,
    int? ngoCount,
    double? campaignGoal,
  }) =>
      CharityState(
        listings: listings ?? this.listings,
        isLoading: isLoading ?? this.isLoading,
        error: error,
        page: page ?? this.page,
        hasMore: hasMore ?? this.hasMore,
        totalRaised: totalRaised ?? this.totalRaised,
        auctionCount: auctionCount ?? this.auctionCount,
        ngoCount: ngoCount ?? this.ngoCount,
        campaignGoal: campaignGoal ?? this.campaignGoal,
      );
}

final charityProvider =
    StateNotifierProvider.autoDispose<CharityNotifier, CharityState>((ref) {
  return CharityNotifier(ref);
});

class CharityNotifier extends StateNotifier<CharityState> {
  CharityNotifier(this._ref) : super(const CharityState()) {
    _loadCampaign();
    loadListings();
  }

  final Ref _ref;

  Future<void> _loadCampaign() async {
    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/charity/campaign');
      final data = resp.data as Map<String, dynamic>;
      state = state.copyWith(
        totalRaised: (data['total_raised'] as num?)?.toDouble() ?? 0,
        auctionCount: data['auction_count'] as int? ?? 0,
        ngoCount: data['ngo_count'] as int? ?? 0,
        campaignGoal: (data['campaign_goal'] as num?)?.toDouble() ?? 10000,
      );
    } catch (_) {
      // Campaign stats are non-critical — use defaults
    }
  }

  Future<void> loadListings({bool refresh = false}) async {
    if (state.isLoading) return;

    final page = refresh ? 1 : state.page;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/listings', queryParameters: {
        'page': page,
        'per_page': 20,
        'status': 'active',
        'is_charity': true,
      });

      final data = resp.data as Map<String, dynamic>;
      final items = (data['items'] as List)
          .map((e) => ListingSummary.fromJson(e as Map<String, dynamic>))
          .toList();

      state = state.copyWith(
        listings: refresh ? items : [...state.listings, ...items],
        isLoading: false,
        page: page + 1,
        hasMore: items.length >= 20,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }

    if (refresh) await _loadCampaign();
  }

  Future<void> refresh() => loadListings(refresh: true);
}

// ═══════════════════════════════════════════════════════════════
// NGO Data
// ═══════════════════════════════════════════════════════════════

class _NgoPartner {
  const _NgoPartner(this.name, this.logoUrl, {this.isZakatEligible = false});
  final String name;
  final String logoUrl;
  final bool isZakatEligible;
}

const _ngoPartners = [
  _NgoPartner('Jordan River Foundation', 'https://cdn.mzadak.com/ngo/jrf.png', isZakatEligible: true),
  _NgoPartner('UNHCR Jordan', 'https://cdn.mzadak.com/ngo/unhcr.png'),
  _NgoPartner('Tkiyet Um Ali', 'https://cdn.mzadak.com/ngo/tkiyet.png', isZakatEligible: true),
  _NgoPartner('King Hussein Cancer Foundation', 'https://cdn.mzadak.com/ngo/khcf.png'),
  _NgoPartner('Noor Al Hussein Foundation', 'https://cdn.mzadak.com/ngo/nhf.png'),
  _NgoPartner('Jordan Hashemite Charity Organization', 'https://cdn.mzadak.com/ngo/jhco.png', isZakatEligible: true),
  _NgoPartner('SOS Children\'s Villages', 'https://cdn.mzadak.com/ngo/sos.png'),
  _NgoPartner('Islamic Charity Center Society', 'https://cdn.mzadak.com/ngo/iccs.png', isZakatEligible: true),
  _NgoPartner('Zain Foundation', 'https://cdn.mzadak.com/ngo/zain.png'),
  _NgoPartner('Al Aman Fund', 'https://cdn.mzadak.com/ngo/alaman.png'),
  _NgoPartner('Madrasati', 'https://cdn.mzadak.com/ngo/madrasati.png'),
  _NgoPartner('Jordan Red Crescent', 'https://cdn.mzadak.com/ngo/redcrescent.png', isZakatEligible: true),
  _NgoPartner('Mercy Corps', 'https://cdn.mzadak.com/ngo/mercycorps.png'),
  _NgoPartner('UNICEF Jordan', 'https://cdn.mzadak.com/ngo/unicef.png'),
];

// ═══════════════════════════════════════════════════════════════
// Screen
// ═══════════════════════════════════════════════════════════════

class CharityScreen extends ConsumerStatefulWidget {
  const CharityScreen({super.key});

  @override
  ConsumerState<CharityScreen> createState() => _CharityScreenState();
}

class _CharityScreenState extends ConsumerState<CharityScreen>
    with TickerProviderStateMixin {
  late AnimationController _counterController;
  late AnimationController _barController;
  late ScrollController _scrollController;

  int _selectedDonation = -1; // -1 = none, 0/1/2 = quick amounts
  final _customAmountController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _counterController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    );
    _barController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _scrollController = ScrollController()..addListener(_onScroll);

    // Start animations after frame renders
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _counterController.forward();
      _barController.forward();
    });
  }

  void _onScroll() {
    if (!_scrollController.hasClients) return;
    final maxScroll = _scrollController.position.maxScrollExtent;
    final current = _scrollController.position.pixels;
    if (current >= maxScroll - 300) {
      final s = ref.read(charityProvider);
      if (!s.isLoading && s.hasMore) {
        ref.read(charityProvider.notifier).loadListings();
      }
    }
  }

  @override
  void dispose() {
    _counterController.dispose();
    _barController.dispose();
    _scrollController.dispose();
    _customAmountController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(charityProvider);

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: _teal,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        title: const Column(
          children: [
            Text(
              'مزاد الخير · Charity Auctions',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                fontFamily: 'Sora',
              ),
            ),
            SizedBox(height: 2),
            Text(
              '100% of proceeds go to verified NGOs · ١٠٠٪ للجمعيات المعتمدة',
              style: TextStyle(
                fontSize: 9,
                fontWeight: FontWeight.w500,
                color: Colors.white70,
              ),
            ),
          ],
        ),
        toolbarHeight: 64,
      ),
      body: MzadakRefreshIndicator(
        onRefresh: () => ref.read(charityProvider.notifier).refresh(),
        child: CustomScrollView(
          controller: _scrollController,
          slivers: [
            // ── Hero Banner ───────────────────────────────────
            SliverToBoxAdapter(child: _HeroBanner(state: state)),

            // ── NGO Partners Row ──────────────────────────────
            const SliverToBoxAdapter(child: _NgoRow()),

            // ── Impact Counter ────────────────────────────────
            SliverToBoxAdapter(
              child: _ImpactCounter(
                state: state,
                counterAnimation: _counterController,
                barAnimation: _barController,
              ),
            ),

            // ── Charity Listings ──────────────────────────────
            SliverPadding(
              padding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm,
              ),
              sliver: SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsetsDirectional.only(
                    top: AppSpacing.md,
                    bottom: AppSpacing.xs,
                  ),
                  child: Row(
                    children: [
                      Container(
                        width: 3,
                        height: 18,
                        decoration: BoxDecoration(
                          color: _teal,
                          borderRadius: AppSpacing.radiusSm,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      const Text(
                        'مزادات خيرية نشطة',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w700,
                          color: AppColors.ink,
                        ),
                      ),
                      const Spacer(),
                      Text(
                        '${state.listings.length} مزاد',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: AppColors.mist,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),

            if (state.listings.isEmpty && !state.isLoading)
              const SliverToBoxAdapter(child: _EmptyCharity()),

            SliverPadding(
              padding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm,
              ),
              sliver: SliverList.builder(
                itemCount: state.listings.length,
                itemBuilder: (context, index) {
                  final listing = state.listings[index];
                  return Padding(
                    padding: const EdgeInsetsDirectional.only(
                      bottom: AppSpacing.sm,
                    ),
                    child: _CharityListingCard(listing: listing),
                  );
                },
              ),
            ),

            if (state.isLoading)
              const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.all(AppSpacing.lg),
                  child: Center(
                    child: SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: _teal,
                      ),
                    ),
                  ),
                ),
              ),

            // ── Donate Directly Section ───────────────────────
            SliverToBoxAdapter(
              child: _DonateDirectly(
                selectedIndex: _selectedDonation,
                customController: _customAmountController,
                onQuickSelect: (i) {
                  HapticFeedback.lightImpact();
                  setState(() => _selectedDonation = i);
                  _customAmountController.clear();
                },
                onCustomChanged: () {
                  if (_customAmountController.text.isNotEmpty) {
                    setState(() => _selectedDonation = -1);
                  }
                },
              ),
            ),

            // Bottom spacing
            const SliverToBoxAdapter(
              child: SizedBox(height: 100),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Hero Banner
// ═══════════════════════════════════════════════════════════════

class _HeroBanner extends StatelessWidget {
  const _HeroBanner({required this.state});
  final CharityState state;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsetsDirectional.all(AppSpacing.sm),
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: AlignmentDirectional.topStart,
          end: AlignmentDirectional.bottomEnd,
          colors: [_teal, _tealDark],
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          // ── Crescent Moon + Star (CustomPainter) ──────────
          SizedBox(
            width: 72,
            height: 72,
            child: CustomPaint(
              painter: _CrescentStarPainter(color: AppColors.gold),
            ),
          ),
          const SizedBox(width: AppSpacing.md),

          // ── Campaign Stats ────────────────────────────────
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Campaign pill
                Container(
                  padding: const EdgeInsetsDirectional.symmetric(
                    horizontal: AppSpacing.xs,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: AppColors.gold,
                    borderRadius: AppSpacing.radiusFull,
                  ),
                  child: const Text(
                    'Ramadan 2026 Campaign',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                      fontFamily: 'Sora',
                      letterSpacing: 0.3,
                    ),
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),

                // Total raised
                Text(
                  '${ArabicNumerals.formatCurrencyEn(state.totalRaised, 'JOD')} raised · تم جمعه',
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: AppColors.gold,
                    fontFamily: 'Sora',
                    height: 1.2,
                  ),
                ),
                const SizedBox(height: AppSpacing.xxs),

                // Auction count
                Text(
                  '${state.auctionCount} auctions · مزاد',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w500,
                    color: Colors.white70,
                  ),
                ),
                const SizedBox(height: 2),

                // NGO count
                Text(
                  '${state.ngoCount} NGOs · جمعية',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w500,
                    color: Colors.white70,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Crescent Moon + Star Painter
// ═══════════════════════════════════════════════════════════════

class _CrescentStarPainter extends CustomPainter {
  _CrescentStarPainter({required this.color});
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.fill;

    final cx = size.width / 2;
    final cy = size.height / 2;
    final r = size.width * 0.42;

    // Outer circle (full moon)
    canvas.drawCircle(Offset(cx, cy), r, paint);

    // Inner circle cutout (crescent) — offset to the right
    final cutoutPaint = Paint()
      ..color = _teal
      ..style = PaintingStyle.fill;
    canvas.drawCircle(
      Offset(cx + r * 0.38, cy - r * 0.08),
      r * 0.78,
      cutoutPaint,
    );

    // Star — 5-pointed, positioned top-right of the crescent opening
    final starCx = cx + r * 0.22;
    final starCy = cy - r * 0.12;
    final starR = r * 0.22;
    _drawStar(canvas, starCx, starCy, starR, paint);
  }

  void _drawStar(
      Canvas canvas, double cx, double cy, double r, Paint paint) {
    final path = Path();
    for (int i = 0; i < 5; i++) {
      final outerAngle = -math.pi / 2 + (2 * math.pi * i / 5);
      final innerAngle = outerAngle + math.pi / 5;
      final outerX = cx + r * math.cos(outerAngle);
      final outerY = cy + r * math.sin(outerAngle);
      final innerX = cx + r * 0.4 * math.cos(innerAngle);
      final innerY = cy + r * 0.4 * math.sin(innerAngle);

      if (i == 0) {
        path.moveTo(outerX, outerY);
      } else {
        path.lineTo(outerX, outerY);
      }
      path.lineTo(innerX, innerY);
    }
    path.close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant _CrescentStarPainter old) => color != old.color;
}

// ═══════════════════════════════════════════════════════════════
// NGO Partners Row
// ═══════════════════════════════════════════════════════════════

class _NgoRow extends StatelessWidget {
  const _NgoRow();

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.sm,
          ),
          child: Row(
            children: [
              const Text(
                'شركاؤنا · NGO Partners',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: AppColors.ink,
                ),
              ),
              const Spacer(),
              GestureDetector(
                onTap: () {
                  HapticFeedback.lightImpact();
                  // Navigate to full NGO list
                },
                child: const Text(
                  'All partners \u2192',
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: _teal,
                  ),
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: AppSpacing.xs),
        SizedBox(
          height: 76,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
            ),
            itemCount: _ngoPartners.length,
            separatorBuilder: (_, __) =>
                const SizedBox(width: AppSpacing.sm),
            itemBuilder: (_, index) {
              final ngo = _ngoPartners[index];
              return SizedBox(
                width: 56,
                child: Column(
                  children: [
                    Container(
                      width: 48,
                      height: 48,
                      decoration: BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: AppColors.sand,
                          width: 1.5,
                        ),
                      ),
                      clipBehavior: Clip.antiAlias,
                      child: CachedNetworkImage(
                        imageUrl: ngo.logoUrl,
                        fit: BoxFit.cover,
                        placeholder: (_, __) => Container(
                          color: AppColors.sand,
                          child: Center(
                            child: Text(
                              ngo.name.substring(0, 1),
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w700,
                                color: _teal,
                              ),
                            ),
                          ),
                        ),
                        errorWidget: (_, __, ___) => Container(
                          color: _tealSurface,
                          child: Center(
                            child: Text(
                              ngo.name.substring(0, 1),
                              style: const TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.w700,
                                color: _teal,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      ngo.name.split(' ').first,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.center,
                      style: const TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.w500,
                        color: AppColors.mist,
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
}

// ═══════════════════════════════════════════════════════════════
// Impact Counter (Animated)
// ═══════════════════════════════════════════════════════════════

class _ImpactCounter extends StatelessWidget {
  const _ImpactCounter({
    required this.state,
    required this.counterAnimation,
    required this.barAnimation,
  });

  final CharityState state;
  final AnimationController counterAnimation;
  final AnimationController barAnimation;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs,
      ),
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        children: [
          // Animated counting number
          AnimatedBuilder(
            animation: counterAnimation,
            builder: (_, __) {
              final value = Curves.easeOutCubic
                      .transform(counterAnimation.value) *
                  state.totalRaised;
              return Text(
                ArabicNumerals.formatCurrencyEn(value, 'JOD'),
                style: const TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w800,
                  color: _teal,
                  fontFamily: 'Sora',
                  height: 1.1,
                ),
              );
            },
          ),
          const SizedBox(height: 2),
          const Text(
            'raised this Ramadan · تم جمعه هذا الشهر',
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              color: AppColors.mist,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),

          // Progress bar
          AnimatedBuilder(
            animation: barAnimation,
            builder: (_, __) {
              final barProgress = Curves.easeOutCubic
                      .transform(barAnimation.value) *
                  state.progress;
              return Column(
                children: [
                  ClipRRect(
                    borderRadius: AppSpacing.radiusFull,
                    child: SizedBox(
                      height: 8,
                      child: Stack(
                        children: [
                          // Background
                          Container(
                            decoration: BoxDecoration(
                              color: _tealSurface,
                              borderRadius: AppSpacing.radiusFull,
                            ),
                          ),
                          // Fill
                          FractionallySizedBox(
                            widthFactor: barProgress,
                            child: Container(
                              decoration: BoxDecoration(
                                gradient: const LinearGradient(
                                  colors: [_teal, _tealLight],
                                ),
                                borderRadius: AppSpacing.radiusFull,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xxs),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        '${(barProgress * 100).toStringAsFixed(1)}%',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: _teal,
                          fontFamily: 'Sora',
                        ),
                      ),
                      Text(
                        'Goal: ${ArabicNumerals.formatCurrencyEn(state.campaignGoal, 'JOD')}',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w500,
                          color: AppColors.mist,
                        ),
                      ),
                    ],
                  ),
                ],
              );
            },
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Charity Listing Card (teal-styled)
// ═══════════════════════════════════════════════════════════════

class _CharityListingCard extends StatelessWidget {
  const _CharityListingCard({required this.listing});
  final ListingSummary listing;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      clipBehavior: Clip.antiAlias,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Teal left border
            Container(width: 3, color: _teal),

            // Image
            ClipRRect(
              borderRadius: const BorderRadiusDirectional.only(
                topStart: Radius.circular(0),
                bottomStart: Radius.circular(0),
              ),
              child: SizedBox(
                width: 110,
                child: Hero(
                  tag: HeroTags.listingImage(listing.id),
                  child: CachedNetworkImage(
                    imageUrl: listing.imageUrl,
                    fit: BoxFit.cover,
                    placeholder: (_, __) =>
                        Container(color: AppColors.sand),
                    errorWidget: (_, __, ___) => Container(
                      color: AppColors.sand,
                      child: const Icon(
                        Icons.image_not_supported_rounded,
                        color: AppColors.mist,
                        size: 24,
                      ),
                    ),
                  ),
                ),
              ),
            ),

            // Content
            Expanded(
              child: Padding(
                padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // Badges row
                    Wrap(
                      spacing: AppSpacing.xxs,
                      runSpacing: AppSpacing.xxs,
                      children: [
                        _TealBadge(
                          label: '0% commission · بدون عمولة',
                          color: _teal,
                        ),
                        // Show zakat badge based on NGO data
                        _TealBadge(
                          label: 'زكاة',
                          color: AppColors.gold,
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xxs),

                    // Title
                    Text(
                      listing.titleAr,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppColors.ink,
                        height: 1.3,
                      ),
                    ),
                    const Spacer(),

                    // Price row
                    Row(
                      children: [
                        Text(
                          ArabicNumerals.formatCurrency(
                            listing.displayPrice,
                            listing.currency,
                          ),
                          style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            color: _teal,
                            fontFamily: 'Sora',
                          ),
                        ),
                        const Spacer(),
                        Text(
                          '${ArabicNumerals.formatNumber(listing.bidCount)} مزايدة',
                          style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w600,
                            color: AppColors.mist,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TealBadge extends StatelessWidget {
  const _TealBadge({required this.label, required this.color});
  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: 6,
        vertical: 2,
      ),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 9,
          fontWeight: FontWeight.w700,
          color: color,
          letterSpacing: 0.2,
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Donate Directly
// ═══════════════════════════════════════════════════════════════

class _DonateDirectly extends StatelessWidget {
  const _DonateDirectly({
    required this.selectedIndex,
    required this.customController,
    required this.onQuickSelect,
    required this.onCustomChanged,
  });

  final int selectedIndex;
  final TextEditingController customController;
  final ValueChanged<int> onQuickSelect;
  final VoidCallback onCustomChanged;

  static const _quickAmounts = [10, 25, 50];

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.md,
      ),
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: _tealSurface,
                  borderRadius: AppSpacing.radiusSm,
                ),
                child: const Icon(
                  Icons.volunteer_activism_rounded,
                  color: _teal,
                  size: 18,
                ),
              ),
              const SizedBox(width: AppSpacing.xs),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'تبرع مباشر · Donate Directly',
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                      ),
                    ),
                    Text(
                      'Can\'t find what you want? Donate directly',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.w500,
                        color: AppColors.mist,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),

          // Quick amount chips
          Row(
            children: List.generate(3, (i) {
              final selected = selectedIndex == i;
              return Expanded(
                child: Padding(
                  padding: EdgeInsetsDirectional.only(
                    end: i < 2 ? AppSpacing.xs : 0,
                  ),
                  child: GestureDetector(
                    onTap: () => onQuickSelect(i),
                    child: AnimatedContainer(
                      duration: AppAnimations.state,
                      curve: Curves.easeOut,
                      padding: const EdgeInsetsDirectional.symmetric(
                        vertical: AppSpacing.sm,
                      ),
                      decoration: BoxDecoration(
                        color: selected ? _teal : _tealSurface,
                        borderRadius: AppSpacing.radiusMd,
                        border: Border.all(
                          color: selected ? _teal : Colors.transparent,
                          width: 1.5,
                        ),
                      ),
                      child: Center(
                        child: Text(
                          '${_quickAmounts[i]} JOD',
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: selected ? Colors.white : _teal,
                            fontFamily: 'Sora',
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              );
            }),
          ),
          const SizedBox(height: AppSpacing.sm),

          // Custom amount field
          TextField(
            controller: customController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            onChanged: (_) => onCustomChanged(),
            textDirection: TextDirection.ltr,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.ink,
              fontFamily: 'Sora',
            ),
            decoration: InputDecoration(
              hintText: 'Custom amount · مبلغ آخر',
              hintStyle: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.mist,
              ),
              suffixText: 'JOD',
              suffixStyle: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: _teal,
                fontFamily: 'Sora',
              ),
              contentPadding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm,
                vertical: AppSpacing.sm,
              ),
              border: OutlineInputBorder(
                borderRadius: AppSpacing.radiusMd,
                borderSide: const BorderSide(color: AppColors.sand),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: AppSpacing.radiusMd,
                borderSide: const BorderSide(color: AppColors.sand),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: AppSpacing.radiusMd,
                borderSide: const BorderSide(color: _teal, width: 1.5),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),

          // Donate button
          SizedBox(
            width: double.infinity,
            height: 48,
            child: ElevatedButton(
              onPressed: () {
                HapticFeedback.mediumImpact();
                // Launch Checkout.com payment flow
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: _teal,
                foregroundColor: Colors.white,
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusMd,
                ),
              ),
              child: const Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.payment_rounded, size: 18),
                  SizedBox(width: AppSpacing.xs),
                  Text(
                    'Donate via Checkout.com \u2192',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      fontFamily: 'Sora',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Empty State
// ═══════════════════════════════════════════════════════════════

class _EmptyCharity extends StatelessWidget {
  const _EmptyCharity();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.symmetric(vertical: AppSpacing.xxl),
      child: Column(
        children: [
          Container(
            width: 64,
            height: 64,
            decoration: BoxDecoration(
              color: _tealSurface,
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.volunteer_activism_rounded,
              color: _teal,
              size: 28,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          const Text(
            'لا توجد مزادات خيرية حالياً',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.ink,
            ),
          ),
          const SizedBox(height: AppSpacing.xxs),
          const Text(
            'تابعنا لمعرفة المزادات الجديدة',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: AppColors.mist,
            ),
          ),
        ],
      ),
    );
  }
}
