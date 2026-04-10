import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../core/router.dart';
import '../../core/theme/colors.dart';

/// MZADAK welcome / onboarding screen.
///
/// Layout:
/// - Top 55 %: three stacked listing cards with slight rotation, staggered
///   slide-up entry (0 / 80 / 160 ms delay, 300 ms easeOutCubic each).
/// - Bottom 45 %: white sheet slides up 400 ms after cards settle, spring
///   cubic-bezier(0, 0.8, 0.3, 1). Contains headline, sub-headline, feature
///   pills, CTA button, and sign-in link.
class WelcomeScreen extends StatefulWidget {
  const WelcomeScreen({super.key});

  @override
  State<WelcomeScreen> createState() => _WelcomeScreenState();
}

class _WelcomeScreenState extends State<WelcomeScreen>
    with TickerProviderStateMixin {
  // ── Card slide-up animations (3 cards, staggered) ──────────────
  late final List<AnimationController> _cardControllers;
  late final List<Animation<Offset>> _cardSlides;
  late final List<Animation<double>> _cardFades;

  // ── Bottom sheet slide-up ──────────────────────────────────────
  late final AnimationController _sheetController;
  late final Animation<Offset> _sheetSlide;

  static const _springCurve = Cubic(0, 0.8, 0.3, 1);

  @override
  void initState() {
    super.initState();

    // Cards: 3 controllers, each 300ms, staggered by 80ms
    _cardControllers = List.generate(3, (_) {
      return AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 300),
      );
    });

    _cardSlides = _cardControllers.map((c) {
      return Tween<Offset>(
        begin: const Offset(0, 0.4),
        end: Offset.zero,
      ).animate(CurvedAnimation(parent: c, curve: Curves.easeOutCubic));
    }).toList();

    _cardFades = _cardControllers.map((c) {
      return Tween<double>(begin: 0, end: 1).animate(
        CurvedAnimation(parent: c, curve: Curves.easeOut),
      );
    }).toList();

    // Sheet: 400ms spring, starts after cards finish
    _sheetController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _sheetSlide = Tween<Offset>(
      begin: const Offset(0, 1),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _sheetController, curve: _springCurve));

    _startSequence();
  }

  Future<void> _startSequence() async {
    // Staggered card entry: 0ms, 80ms, 160ms
    for (var i = 0; i < _cardControllers.length; i++) {
      if (i > 0) await Future.delayed(const Duration(milliseconds: 80));
      if (!mounted) return;
      _cardControllers[i].forward();
    }

    // Wait for last card to finish, then slide sheet up
    await _cardControllers.last.forward().orCancel.catchError((_) {});
    if (!mounted) return;
    _sheetController.forward();
  }

  @override
  void dispose() {
    for (final c in _cardControllers) {
      c.dispose();
    }
    _sheetController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottomPadding = MediaQuery.of(context).padding.bottom;

    return Scaffold(
      backgroundColor: AppColors.navy,
      body: Column(
        children: [
          // ── Top 55%: Illustration cards ─────────────────────────
          Expanded(
            flex: 55,
            child: Center(
              child: _buildCardStack(),
            ),
          ),

          // ── Bottom 45%: White sheet ────────────────────────────
          Expanded(
            flex: 45,
            child: SlideTransition(
              position: _sheetSlide,
              child: Container(
                width: double.infinity,
                decoration: const BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.vertical(
                    top: Radius.circular(28),
                  ),
                ),
                padding: EdgeInsets.fromLTRB(24, 32, 24, bottomPadding + 16),
                child: Column(
                  children: [
                    // Arabic headline
                    const Text(
                      'اربح بثقة',
                      style: TextStyle(
                        fontFamily: 'NotoKufiArabic',
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                        height: 1.3,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 4),

                    // English sub-headline
                    const Text(
                      'Win with confidence',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 14,
                        fontWeight: FontWeight.w400,
                        color: AppColors.mist,
                        height: 1.4,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 20),

                    // Feature pills
                    const Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      alignment: WrapAlignment.center,
                      children: [
                        _FeaturePill(label: '🛡 Smart Escrow'),
                        _FeaturePill(label: '🤖 AI Pricing'),
                        _FeaturePill(label: '📱 WhatsApp Bids'),
                      ],
                    ),

                    const Spacer(),

                    // Primary CTA
                    SizedBox(
                      width: double.infinity,
                      height: 54,
                      child: ElevatedButton(
                        onPressed: _onGetStarted,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.navy,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                          ),
                          elevation: 0,
                          textStyle: const TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 15,
                            fontWeight: FontWeight.w800,
                            height: 1,
                          ),
                        ),
                        child: const Text('Get started · ابدأ الآن'),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // Sign-in link
                    GestureDetector(
                      onTap: _onSignIn,
                      child: Text.rich(
                        TextSpan(
                          text: 'Already have an account? ',
                          style: const TextStyle(
                            fontSize: 12,
                            color: AppColors.mist,
                          ),
                          children: [
                            TextSpan(
                              text: 'Sign in',
                              style: TextStyle(
                                fontSize: 12,
                                color: AppColors.gold,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── Card stack with rotation ─────────────────────────────────────
  Widget _buildCardStack() {
    const rotations = [-3.0, 0.0, 3.0];
    const prices = ['١٢,٠٠٠', '٨,٥٠٠', '١٥,٧٥٠'];

    return SizedBox(
      width: 260,
      height: 200,
      child: Stack(
        alignment: Alignment.center,
        children: List.generate(3, (i) {
          return SlideTransition(
            position: _cardSlides[i],
            child: FadeTransition(
              opacity: _cardFades[i],
              child: Transform.rotate(
                angle: rotations[i] * 3.14159 / 180,
                child: _ListingCard(price: prices[i]),
              ),
            ),
          );
        }),
      ),
    );
  }

  void _onGetStarted() {
    HapticFeedback.mediumImpact();
    context.go(AppRoutes.login);
  }

  void _onSignIn() {
    context.go(AppRoutes.login);
  }
}

// ── Mock listing card for illustration ────────────────────────────

class _ListingCard extends StatelessWidget {
  const _ListingCard({required this.price});
  final String price;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 220,
      height: 140,
      decoration: BoxDecoration(
        color: const Color(0xFF243E62), // navy2 — slightly lighter navy
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withOpacity(0.25),
            blurRadius: 16,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Fake image placeholder lines
          Container(
            width: 80,
            height: 8,
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.12),
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          const SizedBox(height: 8),
          Container(
            width: 120,
            height: 8,
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(0.08),
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          const Spacer(),
          // Gold price badge
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              '$price د.أ',
              style: const TextStyle(
                fontFamily: 'Sora',
                fontSize: 13,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                height: 1,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Feature pill chip ─────────────────────────────────────────────

class _FeaturePill extends StatelessWidget {
  const _FeaturePill({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: AppColors.cream,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontSize: 9,
          fontWeight: FontWeight.w600,
          color: AppColors.gold,
          height: 1.2,
        ),
      ),
    );
  }
}
