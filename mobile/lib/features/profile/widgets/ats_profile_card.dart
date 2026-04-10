import 'package:flutter/material.dart';

import '../../../core/theme/animations.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// ATS (Auction Trust Score) profile card with animated score bars.
///
/// Shows 5 component bars that stagger in from left with 80ms offset:
/// - Identity verification (0-1)
/// - Completion rate (0-1)
/// - Speed (response/shipping) (0-1)
/// - Ratings (0-1)
/// - Dispute-free record (0-1)
///
/// Overall score 0–1000 with tier badge (starter/trusted/pro/elite).
/// Bars animate from 0 → actual value with easeOutCubic.
class AtsProfileCard extends StatefulWidget {
  const AtsProfileCard({
    super.key,
    required this.score,
    required this.tier,
    required this.components,
  });

  final int score;
  final String tier;

  /// Map of component name → normalized value (0.0 to 1.0).
  final List<AtsComponent> components;

  @override
  State<AtsProfileCard> createState() => _AtsProfileCardState();
}

class AtsComponent {
  const AtsComponent({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final double value; // 0.0 to 1.0
  final IconData icon;
}

class _AtsProfileCardState extends State<AtsProfileCard>
    with TickerProviderStateMixin {
  final List<AnimationController> _barControllers = [];
  final List<Animation<double>> _barAnimations = [];

  // Score counter
  late AnimationController _scoreController;
  late Animation<double> _scoreAnimation;

  @override
  void initState() {
    super.initState();

    // Score count-up from 0 → actual
    _scoreController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
    _scoreAnimation = Tween<double>(
      begin: 0,
      end: widget.score.toDouble(),
    ).animate(CurvedAnimation(
      parent: _scoreController,
      curve: Curves.easeOutCubic,
    ));

    // Bar animations — one per component
    for (var i = 0; i < widget.components.length; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 600),
      );
      final animation = Tween<double>(
        begin: 0,
        end: widget.components[i].value,
      ).animate(CurvedAnimation(
        parent: controller,
        curve: Curves.easeOutCubic,
      ));
      _barControllers.add(controller);
      _barAnimations.add(animation);
    }

    _startStaggeredEntry();
  }

  Future<void> _startStaggeredEntry() async {
    // Score counter starts immediately
    _scoreController.forward();

    // Bars stagger in with 80ms offset
    for (var i = 0; i < _barControllers.length; i++) {
      if (!mounted) return;
      _barControllers[i].forward();
      if (i < _barControllers.length - 1) {
        await Future.delayed(const Duration(milliseconds: 80));
      }
    }
  }

  @override
  void dispose() {
    _scoreController.dispose();
    for (final c in _barControllers) {
      c.dispose();
    }
    super.dispose();
  }

  Color get _tierColor => switch (widget.tier) {
        'elite' => AppColors.emerald,
        'pro' => AppColors.gold,
        'trusted' => AppColors.navy,
        _ => AppColors.mist,
      };

  String get _tierLabel => switch (widget.tier) {
        'elite' => 'نخبة',
        'pro' => 'محترف',
        'trusted' => 'موثوق',
        _ => 'مبتدئ',
      };

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: AppSpacing.radiusLg,
        border: Border.all(color: AppColors.sand),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Score header ─────────────────────────────────────────
          Row(
            children: [
              // Score circle
              AnimatedBuilder(
                animation: _scoreAnimation,
                builder: (_, __) => _ScoreCircle(
                  score: _scoreAnimation.value.round(),
                  maxScore: 1000,
                  color: _tierColor,
                ),
              ),
              const SizedBox(width: AppSpacing.md),

              // Tier info
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'نقاط الثقة',
                      style: TextStyle(
                        fontSize: 13,
                        color: AppColors.mist,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsetsDirectional.symmetric(
                            horizontal: 8,
                            vertical: 3,
                          ),
                          decoration: BoxDecoration(
                            color: _tierColor.withOpacity(0.12),
                            borderRadius: AppSpacing.radiusSm,
                          ),
                          child: Text(
                            _tierLabel,
                            style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w700,
                              color: _tierColor,
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

          const SizedBox(height: AppSpacing.lg),

          // ── Component bars ───────────────────────────────────────
          ...List.generate(widget.components.length, (i) {
            return Padding(
              padding: EdgeInsetsDirectional.only(
                bottom: i < widget.components.length - 1 ? AppSpacing.sm : 0,
              ),
              child: AnimatedBuilder(
                animation: _barAnimations[i],
                builder: (_, __) => _ComponentBar(
                  label: widget.components[i].label,
                  icon: widget.components[i].icon,
                  value: _barAnimations[i].value,
                  color: _barColor(_barAnimations[i].value),
                ),
              ),
            );
          }),
        ],
      ),
    );
  }

  /// Color based on bar fill: low=ember, mid=gold, high=emerald.
  Color _barColor(double value) {
    if (value >= 0.8) return AppColors.emerald;
    if (value >= 0.5) return AppColors.gold;
    return AppColors.ember;
  }
}

/// Circular score display with animated ring.
class _ScoreCircle extends StatelessWidget {
  const _ScoreCircle({
    required this.score,
    required this.maxScore,
    required this.color,
  });

  final int score;
  final int maxScore;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 64,
      height: 64,
      child: Stack(
        fit: StackFit.expand,
        children: [
          // Background ring
          CircularProgressIndicator(
            value: 1.0,
            strokeWidth: 5,
            backgroundColor: Colors.transparent,
            valueColor: AlwaysStoppedAnimation(AppColors.sand),
          ),
          // Foreground ring
          CircularProgressIndicator(
            value: score / maxScore,
            strokeWidth: 5,
            backgroundColor: Colors.transparent,
            valueColor: AlwaysStoppedAnimation(color),
            strokeCap: StrokeCap.round,
          ),
          // Score text
          Center(
            child: Text(
              '$score',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w800,
                color: color,
                fontFamily: 'Sora',
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Single ATS component bar with label, icon, and animated fill.
class _ComponentBar extends StatelessWidget {
  const _ComponentBar({
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
        // Label row
        Row(
          children: [
            Icon(icon, size: 14, color: AppColors.mist),
            const SizedBox(width: AppSpacing.xs),
            Text(
              label,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: AppColors.ink,
              ),
            ),
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
        const SizedBox(height: AppSpacing.xxs),

        // Bar
        ClipRRect(
          borderRadius: AppSpacing.radiusFull,
          child: SizedBox(
            height: 8,
            child: Stack(
              children: [
                // Background
                Container(
                  width: double.infinity,
                  color: AppColors.sand,
                ),
                // Fill
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

/// Default ATS components matching the spec:
/// identity, completion rate, speed, ratings, dispute-free.
List<AtsComponent> defaultAtsComponents({
  double identity = 1.0,
  double completionRate = 0.0,
  double speed = 0.0,
  double ratings = 0.0,
  double disputeFree = 1.0,
}) =>
    [
      AtsComponent(
        label: 'التحقق من الهوية',
        value: identity,
        icon: Icons.verified_user_rounded,
      ),
      AtsComponent(
        label: 'نسبة الإتمام',
        value: completionRate,
        icon: Icons.check_circle_rounded,
      ),
      AtsComponent(
        label: 'سرعة الاستجابة',
        value: speed,
        icon: Icons.speed_rounded,
      ),
      AtsComponent(
        label: 'التقييمات',
        value: ratings,
        icon: Icons.star_rounded,
      ),
      AtsComponent(
        label: 'سجل خالٍ من النزاعات',
        value: disputeFree,
        icon: Icons.shield_rounded,
      ),
    ];
