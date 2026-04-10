import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/l10n/arabic_numerals.dart';
import '../core/providers/core_providers.dart';
import '../core/theme/animations.dart';
import '../core/theme/colors.dart';
import '../core/theme/spacing.dart';

// ═══════════════════════════════════════════════════════════════════════
//  ATS Profile Screen — SDD §5.4
// ═══════════════════════════════════════════════════════════════════════
//
//  GET /api/v1/auth/me → full ATS breakdown with 6 signal scores
//  Score: counts up (score-120)→score over 1200ms easeOutCubic
//  Signal bars: 6 bars stagger via Interval on single controller
//  Tier: Elite ≥750, Gold 600-749, Silver 400-599, Bronze <400
//  Perks: total sales, rating, disputes, commission
//  Recent sales: GET /listings?seller_id=me&status=ended&limit=3
//  Elite banner: SlideTransition Offset(0,0.4) with 450ms delay
// ═══════════════════════════════════════════════════════════════════════

/// Tier enum derived from score.
enum AtsTier {
  elite,
  gold,
  silver,
  bronze;

  static AtsTier fromScore(int score) {
    if (score >= 750) return AtsTier.elite;
    if (score >= 600) return AtsTier.gold;
    if (score >= 400) return AtsTier.silver;
    return AtsTier.bronze;
  }

  String get labelAr => switch (this) {
        AtsTier.elite => 'Elite · نخبة',
        AtsTier.gold => 'Gold · ذهبي',
        AtsTier.silver => 'Silver · فضي',
        AtsTier.bronze => 'Bronze · برونزي',
      };

  IconData get icon => switch (this) {
        AtsTier.elite => Icons.diamond_rounded,
        AtsTier.gold => Icons.workspace_premium_rounded,
        AtsTier.silver => Icons.verified_user_rounded,
        AtsTier.bronze => Icons.person_rounded,
      };

  Color get color => switch (this) {
        AtsTier.elite => AppColors.emerald,
        AtsTier.gold => AppColors.gold,
        AtsTier.silver => AppColors.navy,
        AtsTier.bronze => AppColors.mist,
      };

  double get commissionRate => switch (this) {
        AtsTier.elite => 0.04,
        AtsTier.gold => 0.05,
        AtsTier.silver => 0.055,
        AtsTier.bronze => 0.06,
      };
}

/// ATS signal definition with label, score 0.0-1.0, and category for color.
class AtsSignal {
  const AtsSignal({
    required this.label,
    required this.value,
    required this.category,
  });

  final String label;
  final double value;
  final String category;
}

/// Recent sale item.
class RecentSale {
  const RecentSale({
    required this.title,
    required this.price,
    required this.currency,
    required this.buyerRating,
    required this.date,
  });

  final String title;
  final double price;
  final String currency;
  final double buyerRating;
  final DateTime date;

  factory RecentSale.fromJson(Map<String, dynamic> json) => RecentSale(
        title: json['title_ar'] as String? ?? json['title'] as String? ?? '',
        price: (json['final_price'] as num?)?.toDouble() ?? 0,
        currency: json['currency'] as String? ?? 'JOD',
        buyerRating: (json['buyer_rating'] as num?)?.toDouble() ?? 0,
        date: DateTime.tryParse(json['ended_at'] as String? ?? '') ??
            DateTime.now(),
      );
}

/// Full ATS profile data from GET /auth/me.
class AtsProfile {
  const AtsProfile({
    required this.score,
    required this.previousScore,
    required this.nameAr,
    this.avatarUrl,
    this.coverUrl,
    this.isVerified = true,
    this.memberSince,
    this.rank,
    this.totalUsers,
    this.identityScore = 0,
    this.completionScore = 0,
    this.speedScore = 0,
    this.ratingScore = 0,
    this.qualityScore = 0,
    this.disputeScore = 0,
    this.totalSales = 0,
    this.avgRating = 0,
    this.disputeCount = 0,
    this.recentSales = const [],
  });

  final int score;
  final int previousScore;
  final String nameAr;
  final String? avatarUrl;
  final String? coverUrl;
  final bool isVerified;
  final String? memberSince;
  final int? rank;
  final int? totalUsers;
  final double identityScore;
  final double completionScore;
  final double speedScore;
  final double ratingScore;
  final double qualityScore;
  final double disputeScore;
  final int totalSales;
  final double avgRating;
  final int disputeCount;
  final List<RecentSale> recentSales;

  int get scoreChange => score - previousScore;

  AtsTier get tier => AtsTier.fromScore(score);

  List<AtsSignal> get signals => [
        AtsSignal(
            label: 'التحقق من الهوية',
            value: identityScore,
            category: 'identity'),
        AtsSignal(
            label: 'اكتمال الملف',
            value: completionScore,
            category: 'completion'),
        AtsSignal(
            label: 'سرعة الشحن',
            value: speedScore,
            category: 'speed'),
        AtsSignal(
            label: 'تقييمات المشترين',
            value: ratingScore,
            category: 'ratings'),
        AtsSignal(
            label: 'جودة القوائم',
            value: qualityScore,
            category: 'quality'),
        AtsSignal(
            label: 'النزاعات',
            value: disputeScore,
            category: 'disputes'),
      ];

  factory AtsProfile.fromJson(Map<String, dynamic> json) => AtsProfile(
        score: json['ats_score'] as int? ?? 0,
        previousScore: json['ats_previous_score'] as int? ?? 0,
        nameAr: json['name_ar'] as String? ?? '',
        avatarUrl: json['avatar_url'] as String?,
        coverUrl: json['cover_url'] as String?,
        isVerified: json['is_verified'] as bool? ?? false,
        memberSince: json['member_since'] as String?,
        rank: json['ats_rank'] as int?,
        totalUsers: json['total_users'] as int?,
        identityScore:
            (json['ats_identity_score'] as num?)?.toDouble() ?? 0,
        completionScore:
            (json['ats_completion_score'] as num?)?.toDouble() ?? 0,
        speedScore:
            (json['ats_speed_score'] as num?)?.toDouble() ?? 0,
        ratingScore:
            (json['ats_rating_score'] as num?)?.toDouble() ?? 0,
        qualityScore:
            (json['ats_quality_score'] as num?)?.toDouble() ?? 0,
        disputeScore:
            (json['ats_dispute_score'] as num?)?.toDouble() ?? 0,
        totalSales: json['total_sales'] as int? ?? 0,
        avgRating: (json['avg_rating'] as num?)?.toDouble() ?? 0,
        disputeCount: json['dispute_count'] as int? ?? 0,
      );
}

class AtsProfileScreen extends ConsumerStatefulWidget {
  const AtsProfileScreen({super.key, this.userId});

  /// If null, loads own profile via GET /auth/me.
  final String? userId;

  @override
  ConsumerState<AtsProfileScreen> createState() => _AtsProfileScreenState();
}

class _AtsProfileScreenState extends ConsumerState<AtsProfileScreen>
    with TickerProviderStateMixin {
  AtsProfile? _profile;
  bool _isLoading = true;
  String? _error;

  // ── Score card scale entrance ──────────────────────────────────
  late AnimationController _scoreScaleController;
  late Animation<double> _scoreScale;

  // ── Score count-up ─────────────────────────────────────────────
  late AnimationController _scoreCountController;

  // ── Signal bars: single controller with Interval stagger ───────
  late AnimationController _staggerCtrl;
  final List<Animation<double>> _barAnims = [];

  // ── Perks row fade ─────────────────────────────────────────────
  late AnimationController _perksFadeController;
  late Animation<double> _perksFade;

  // ── Elite banner slide-up ──────────────────────────────────────
  late AnimationController _eliteCtrl;
  late Animation<Offset> _eliteSlide;

  @override
  void initState() {
    super.initState();

    // Score card: scale 0.92 → 1.0
    _scoreScaleController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _scoreScale = Tween<double>(begin: 0.92, end: 1.0).animate(
      CurvedAnimation(
          parent: _scoreScaleController, curve: Curves.easeOutCubic),
    );

    // Score count-up: (score-120) → score over 1200ms
    _scoreCountController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );

    // Stagger controller for all 6 bars
    _staggerCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1600),
    );

    // Build 6 bar animations with Interval stagger (80ms = 0.05 of 1600ms)
    for (var i = 0; i < 6; i++) {
      final start = i * 0.08;
      final end = (start + 0.50).clamp(0.0, 1.0);
      _barAnims.add(
        CurvedAnimation(
          parent: _staggerCtrl,
          curve: Interval(start, end, curve: Curves.easeOutCubic),
        ),
      );
    }

    // Perks fade
    _perksFadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _perksFade = CurvedAnimation(
        parent: _perksFadeController, curve: Curves.easeOut);

    // Elite banner
    _eliteCtrl = AnimationController(
      vsync: this,
      duration: AppAnimations.enter,
    );
    _eliteSlide = Tween<Offset>(
      begin: const Offset(0, 0.4),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _eliteCtrl,
      curve: const Cubic(0, 0.8, 0.3, 1),
    ));

    _loadProfile();
  }

  @override
  void dispose() {
    _scoreScaleController.dispose();
    _scoreCountController.dispose();
    _staggerCtrl.dispose();
    _perksFadeController.dispose();
    _eliteCtrl.dispose();
    super.dispose();
  }

  // ── Data loading ──────────────────────────────────────────────────

  Future<void> _loadProfile() async {
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.get('/auth/me');
      final data = resp.data as Map<String, dynamic>;
      final profile = AtsProfile.fromJson(data);

      // Load recent sales
      List<RecentSale> sales = [];
      try {
        final salesResp = await api.get(
          '/listings',
          queryParameters: {
            'seller_id': 'me',
            'status': 'ended',
            'limit': 3,
          },
        );
        final salesData = salesResp.data as Map<String, dynamic>;
        sales = (salesData['listings'] as List? ?? [])
            .map((e) => RecentSale.fromJson(e as Map<String, dynamic>))
            .toList();
      } catch (_) {
        // Non-critical
      }

      if (!mounted) return;

      setState(() {
        _profile = AtsProfile(
          score: profile.score,
          previousScore: profile.previousScore,
          nameAr: profile.nameAr,
          avatarUrl: profile.avatarUrl,
          coverUrl: profile.coverUrl,
          isVerified: profile.isVerified,
          memberSince: profile.memberSince,
          rank: profile.rank,
          totalUsers: profile.totalUsers,
          identityScore: profile.identityScore,
          completionScore: profile.completionScore,
          speedScore: profile.speedScore,
          ratingScore: profile.ratingScore,
          qualityScore: profile.qualityScore,
          disputeScore: profile.disputeScore,
          totalSales: profile.totalSales,
          avgRating: profile.avgRating,
          disputeCount: profile.disputeCount,
          recentSales: sales,
        );
        _isLoading = false;
      });

      _runEntrySequence();
    } catch (e) {
      if (mounted) {
        setState(() {
          _isLoading = false;
          _error = e.toString();
        });
      }
    }
  }

  // ── Entrance sequence ─────────────────────────────────────────────

  Future<void> _runEntrySequence() async {
    if (_profile == null) return;

    // 1. Score card scales in
    _scoreScaleController.forward();
    await Future.delayed(const Duration(milliseconds: 300));

    // 2. Score counts up
    if (mounted) _scoreCountController.forward();
    await Future.delayed(const Duration(milliseconds: 400));

    // 3. Bars stagger in
    if (mounted) _staggerCtrl.forward();
    await Future.delayed(const Duration(milliseconds: 800));

    // 4. Perks row fades in
    if (mounted) _perksFadeController.forward();
    await Future.delayed(const Duration(milliseconds: 250));

    // 5. Elite banner slides up (450ms after perks)
    if (mounted && _profile!.tier == AtsTier.elite) {
      await Future.delayed(const Duration(milliseconds: 450));
      if (mounted) _eliteCtrl.forward();
    }
  }

  // ── Color helpers ─────────────────────────────────────────────────

  Color _signalColor(String category) => switch (category) {
        'identity' || 'completion' || 'disputes' => AppColors.emerald,
        'speed' || 'ratings' => const Color(0xFF4A9BD9), // sky
        'quality' => AppColors.gold,
        _ => AppColors.navy,
      };

  // ── Build ─────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Scaffold(
        backgroundColor: AppColors.cream,
        body: const Center(
          child: CircularProgressIndicator(
            valueColor: AlwaysStoppedAnimation(AppColors.navy),
          ),
        ),
      );
    }

    if (_error != null || _profile == null) {
      return Scaffold(
        backgroundColor: AppColors.cream,
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          foregroundColor: AppColors.navy,
        ),
        body: Center(
          child: Text(
            _error ?? 'حدث خطأ',
            style: const TextStyle(color: AppColors.ember),
          ),
        ),
      );
    }

    final profile = _profile!;

    return Scaffold(
      body: Stack(
        children: [
          CustomScrollView(
            slivers: [
              // ── Hero header ──────────────────────────────────────
              SliverToBoxAdapter(child: _buildHeroHeader(profile)),

              // ── Score section ────────────────────────────────────
              SliverToBoxAdapter(
                child: Padding(
                  padding: AppSpacing.allMd,
                  child: ScaleTransition(
                    scale: _scoreScale,
                    child: _buildScoreSection(profile),
                  ),
                ),
              ),

              // ── Signal bars ──────────────────────────────────────
              SliverToBoxAdapter(
                child: Padding(
                  padding: AppSpacing.horizontalMd,
                  child: _buildSignalBars(profile),
                ),
              ),

              // ── Tier badge ───────────────────────────────────────
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsetsDirectional.all(AppSpacing.md),
                  child: _buildTierBadge(profile),
                ),
              ),

              // ── Perks row ────────────────────────────────────────
              SliverToBoxAdapter(
                child: FadeTransition(
                  opacity: _perksFade,
                  child: Padding(
                    padding: AppSpacing.horizontalMd,
                    child: _buildPerksRow(profile),
                  ),
                ),
              ),

              // ── Recent sales ─────────────────────────────────────
              if (profile.recentSales.isNotEmpty)
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsetsDirectional.all(AppSpacing.md),
                    child: _buildRecentSales(profile),
                  ),
                ),

              // Bottom padding for elite banner
              const SliverToBoxAdapter(
                child: SizedBox(height: 100),
              ),
            ],
          ),

          // ── Elite banner ──────────────────────────────────────────
          if (profile.tier == AtsTier.elite)
            Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: SlideTransition(
                position: _eliteSlide,
                child: const _EliteBanner(),
              ),
            ),
        ],
      ),
    );
  }

  // ── Hero header ───────────────────────────────────────────────────

  Widget _buildHeroHeader(AtsProfile profile) {
    return SizedBox(
      height: 220,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          // Cover photo
          if (profile.coverUrl != null)
            Positioned.fill(
              child: CachedNetworkImage(
                imageUrl: profile.coverUrl!,
                fit: BoxFit.cover,
              ),
            )
          else
            Container(color: AppColors.navy),

          // Gold stripe at bottom
          Positioned(
            bottom: 0,
            left: 0,
            right: 0,
            height: 4,
            child: Container(color: AppColors.gold),
          ),

          // Back button
          Positioned(
            top: MediaQuery.of(context).padding.top + AppSpacing.xs,
            left: AppSpacing.sm,
            child: IconButton(
              onPressed: () => Navigator.of(context).maybePop(),
              icon: const Icon(Icons.arrow_back_ios_new_rounded),
              color: Colors.white,
              style: IconButton.styleFrom(
                backgroundColor: Colors.black26,
              ),
            ),
          ),

          // Avatar with verification badge
          Positioned(
            bottom: -36,
            left: 0,
            right: 0,
            child: Center(
              child: Stack(
                children: [
                  Container(
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 4),
                      color: profile.tier.color.withOpacity(0.15),
                    ),
                    child: profile.avatarUrl != null
                        ? ClipOval(
                            child: CachedNetworkImage(
                              imageUrl: profile.avatarUrl!,
                              fit: BoxFit.cover,
                            ),
                          )
                        : Icon(Icons.person,
                            color: profile.tier.color, size: 36),
                  ),
                  if (profile.isVerified)
                    Positioned(
                      bottom: 0,
                      right: 0,
                      child: Container(
                        width: 24,
                        height: 24,
                        decoration: const BoxDecoration(
                          color: AppColors.emerald,
                          shape: BoxShape.circle,
                          border: Border.fromBorderSide(
                              BorderSide(color: Colors.white, width: 2)),
                        ),
                        child: const Icon(Icons.check,
                            color: Colors.white, size: 14),
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

  // ── Score section ─────────────────────────────────────────────────

  Widget _buildScoreSection(AtsProfile profile) {
    final beginScore = (profile.score - 120).clamp(0, 999);

    return Column(
      children: [
        const SizedBox(height: 40),
        Text(
          profile.nameAr,
          style: const TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.ink,
          ),
        ),
        if (profile.memberSince != null) ...[
          const SizedBox(height: 2),
          Text(
            'عضو منذ ${profile.memberSince}',
            style: const TextStyle(fontSize: 13, color: AppColors.mist),
          ),
        ],
        const SizedBox(height: AppSpacing.lg),

        // Score count-up: (score-120) → score over 1200ms
        AnimatedBuilder(
          animation: CurvedAnimation(
            parent: _scoreCountController,
            curve: Curves.easeOutCubic,
          ),
          builder: (_, __) {
            final t = CurvedAnimation(
              parent: _scoreCountController,
              curve: Curves.easeOutCubic,
            ).value;
            final currentScore =
                (beginScore + (profile.score - beginScore) * t).round();
            return Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$currentScore',
                      style: TextStyle(
                        fontSize: 48,
                        fontWeight: FontWeight.w900,
                        color: profile.tier.color,
                        fontFamily: 'Sora',
                        height: 1,
                      ),
                    ),
                    // Score change badge
                    if (profile.scoreChange != 0) ...[
                      const SizedBox(width: 8),
                      Container(
                        margin: const EdgeInsets.only(top: 4),
                        padding: const EdgeInsetsDirectional.symmetric(
                            horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: profile.scoreChange > 0
                              ? AppColors.emerald
                              : AppColors.ember,
                          borderRadius: AppSpacing.radiusSm,
                        ),
                        child: Text(
                          profile.scoreChange > 0
                              ? '+${profile.scoreChange}'
                              : '${profile.scoreChange}',
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w700,
                            color: Colors.white,
                            fontFamily: 'Sora',
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 4),
                SizedBox(
                  width: 120,
                  child: ClipRRect(
                    borderRadius: AppSpacing.radiusFull,
                    child: LinearProgressIndicator(
                      value: currentScore / 1000,
                      minHeight: 8,
                      backgroundColor: AppColors.sand,
                      valueColor:
                          AlwaysStoppedAnimation(profile.tier.color),
                    ),
                  ),
                ),
              ],
            );
          },
        ),
        const SizedBox(height: AppSpacing.xxs),
        const Text(
          'من ١٠٠٠',
          style: TextStyle(fontSize: 12, color: AppColors.mist),
        ),
      ],
    );
  }

  // ── Signal bars ───────────────────────────────────────────────────

  Widget _buildSignalBars(AtsProfile profile) {
    final signals = profile.signals;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'تفاصيل النقاط',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        ...List.generate(signals.length, (i) {
          final signal = signals[i];
          return Padding(
            padding: EdgeInsetsDirectional.only(
              bottom: i < signals.length - 1 ? AppSpacing.md : 0,
            ),
            child: AnimatedBuilder(
              animation: _barAnims[i],
              builder: (_, __) {
                final val = _barAnims[i].value * signal.value;
                return _buildBarRow(
                    signal.label, val, _signalColor(signal.category));
              },
            ),
          );
        }),
      ],
    );
  }

  Widget _buildBarRow(String label, double value, Color color) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Text(label,
                style: const TextStyle(fontSize: 13, color: AppColors.ink)),
            const Spacer(),
            Text(
              '${(value * 100).toInt()}',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: color,
                fontFamily: 'Sora',
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),
        LayoutBuilder(
          builder: (_, constraints) {
            return Stack(
              children: [
                Container(
                  width: double.infinity,
                  height: 8,
                  decoration: BoxDecoration(
                    color: AppColors.sand,
                    borderRadius: AppSpacing.radiusFull,
                  ),
                ),
                Container(
                  width: constraints.maxWidth * value.clamp(0.0, 1.0),
                  height: 8,
                  decoration: BoxDecoration(
                    color: color,
                    borderRadius: AppSpacing.radiusFull,
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  // ── Tier badge ────────────────────────────────────────────────────

  Widget _buildTierBadge(AtsProfile profile) {
    final tier = profile.tier;

    return Row(
      children: [
        // Rank
        Expanded(
          child: Container(
            padding: AppSpacing.allMd,
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: AppSpacing.radiusMd,
              border: Border.all(color: AppColors.sand),
            ),
            child: Column(
              children: [
                const Icon(Icons.leaderboard_rounded,
                    color: AppColors.navy, size: 24),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  profile.rank != null ? '#${profile.rank}' : '-',
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    color: AppColors.navy,
                    fontFamily: 'Sora',
                  ),
                ),
                const Text('الترتيب',
                    style: TextStyle(fontSize: 12, color: AppColors.mist)),
              ],
            ),
          ),
        ),
        const SizedBox(width: AppSpacing.sm),
        // Tier
        Expanded(
          child: Container(
            padding: AppSpacing.allMd,
            decoration: BoxDecoration(
              color: tier.color.withOpacity(0.06),
              borderRadius: AppSpacing.radiusMd,
              border: Border.all(color: tier.color.withOpacity(0.2)),
            ),
            child: Column(
              children: [
                Icon(tier.icon, color: tier.color, size: 24),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  tier.labelAr,
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w800,
                    color: tier.color,
                  ),
                  textAlign: TextAlign.center,
                ),
                const Text('المستوى',
                    style: TextStyle(fontSize: 12, color: AppColors.mist)),
              ],
            ),
          ),
        ),
      ],
    );
  }

  // ── Perks row (4 cards) ───────────────────────────────────────────

  Widget _buildPerksRow(AtsProfile profile) {
    final tier = profile.tier;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'إحصائيات',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        Row(
          children: [
            _PerkCard(
              icon: Icons.shopping_bag_rounded,
              label: 'المبيعات',
              value: '${profile.totalSales}',
              color: AppColors.navy,
            ),
            const SizedBox(width: AppSpacing.xs),
            _PerkCard(
              icon: Icons.star_rounded,
              label: 'التقييم',
              value: profile.avgRating.toStringAsFixed(1),
              color: AppColors.gold,
            ),
            const SizedBox(width: AppSpacing.xs),
            _PerkCard(
              icon: Icons.gavel_rounded,
              label: 'النزاعات',
              value: '${profile.disputeCount}',
              color: profile.disputeCount == 0
                  ? AppColors.emerald
                  : AppColors.ember,
            ),
            const SizedBox(width: AppSpacing.xs),
            _PerkCard(
              icon: Icons.percent_rounded,
              label: 'العمولة',
              value: '${(tier.commissionRate * 100).toStringAsFixed(tier == AtsTier.silver ? 1 : 0)}%',
              color: tier.color,
            ),
          ],
        ),
      ],
    );
  }

  // ── Recent sales ──────────────────────────────────────────────────

  Widget _buildRecentSales(AtsProfile profile) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'آخر المبيعات',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        ...profile.recentSales.map((sale) => Padding(
              padding:
                  const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
              child: Container(
                padding: AppSpacing.allSm,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: AppSpacing.radiusMd,
                  border: Border.all(color: AppColors.sand),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            sale.title,
                            style: const TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: AppColors.ink,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: 2),
                          Text(
                            _formatRelativeDate(sale.date),
                            style: const TextStyle(
                                fontSize: 12, color: AppColors.mist),
                          ),
                        ],
                      ),
                    ),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          ArabicNumerals.formatCurrency(
                              sale.price, sale.currency),
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                            color: AppColors.gold,
                            fontFamily: 'Sora',
                          ),
                        ),
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.star_rounded,
                                color: AppColors.gold, size: 14),
                            const SizedBox(width: 2),
                            Text(
                              sale.buyerRating.toStringAsFixed(1),
                              style: const TextStyle(
                                fontSize: 12,
                                color: AppColors.mist,
                                fontFamily: 'Sora',
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            )),
      ],
    );
  }

  String _formatRelativeDate(DateTime date) {
    final diff = DateTime.now().difference(date);
    if (diff.inDays == 0) return 'Today';
    if (diff.inDays == 1) return 'Yesterday';
    if (diff.inDays < 7) return '${diff.inDays} days ago';
    return '${date.day}/${date.month}/${date.year}';
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Perk card
// ═══════════════════════════════════════════════════════════════════════

class _PerkCard extends StatelessWidget {
  const _PerkCard({
    required this.icon,
    required this.label,
    required this.value,
    required this.color,
  });

  final IconData icon;
  final String label;
  final String value;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.xs, vertical: AppSpacing.sm),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(color: AppColors.sand),
        ),
        child: Column(
          children: [
            Icon(icon, color: color, size: 20),
            const SizedBox(height: 4),
            Text(
              value,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w800,
                color: color,
                fontFamily: 'Sora',
              ),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              style: const TextStyle(fontSize: 10, color: AppColors.mist),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Elite banner — slides up from bottom
// ═══════════════════════════════════════════════════════════════════════

class _EliteBanner extends StatelessWidget {
  const _EliteBanner();

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsetsDirectional.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.md,
        ),
        margin: EdgeInsetsDirectional.only(
          start: AppSpacing.md,
          end: AppSpacing.md,
          bottom: MediaQuery.of(context).viewPadding.bottom + AppSpacing.md,
        ),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [AppColors.navy, Color(0xFF2A4A6E)],
          ),
          borderRadius: AppSpacing.radiusMd,
          boxShadow: [
            BoxShadow(
              color: AppColors.navy.withOpacity(0.3),
              blurRadius: 16,
              offset: const Offset(0, 4),
            ),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.diamond_rounded,
                color: AppColors.gold, size: 24),
            const SizedBox(width: AppSpacing.sm),
            const Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'مرحباً بك في النخبة',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: Colors.white,
                  ),
                ),
                Text(
                  'أنت ضمن أعلى ١٪ من البائعين',
                  style: TextStyle(fontSize: 12, color: Color(0xFFB0C4DE)),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
