import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/router.dart';
import '../../core/theme/colors.dart';

/// MZADAK brand splash screen — pure brand moment, no skip.
///
/// Sequence:
/// 1. Logo mark (gold rounded square with "M") scales in:
///    scale(0.6) → scale(1.05) → scale(1.0), 600ms, Curves.elasticOut
/// 2. Arabic wordmark "مزادك" fades in 200ms after logo settles (at ~600ms)
/// 3. After 1800ms total: navigates to WelcomeScreen with 400ms fade
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with TickerProviderStateMixin {
  // ── Logo scale: 0.6 → 1.05 → 1.0 spring over 600ms ─────────────
  late AnimationController _logoController;
  late Animation<double> _logoScale;

  // ── Wordmark fade: 0 → 1 over 200ms, starts after logo settles ──
  late AnimationController _wordmarkController;
  late Animation<double> _wordmarkOpacity;

  @override
  void initState() {
    super.initState();

    _logoController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _logoScale = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0.6, end: 1.05), weight: 50),
      TweenSequenceItem(tween: Tween(begin: 1.05, end: 0.95), weight: 25),
      TweenSequenceItem(tween: Tween(begin: 0.95, end: 1.0), weight: 25),
    ]).animate(
      CurvedAnimation(parent: _logoController, curve: Curves.easeOut),
    );

    _wordmarkController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 200),
    );
    _wordmarkOpacity = CurvedAnimation(
      parent: _wordmarkController,
      curve: Curves.easeOut,
    );

    // Start sequence
    _logoController.forward();

    // Wordmark fades in after logo settles (~600ms)
    _logoController.addStatusListener((status) {
      if (status == AnimationStatus.completed && mounted) {
        _wordmarkController.forward();
      }
    });

    // Navigate after 1800ms total
    Future.delayed(const Duration(milliseconds: 1800), _navigateToWelcome);
  }

  void _navigateToWelcome() {
    if (!mounted) return;
    context.go(AppRoutes.welcome);
  }

  @override
  void dispose() {
    _logoController.dispose();
    _wordmarkController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.navy,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // ── Logo mark: gold rounded square with "M" ───────────
            AnimatedBuilder(
              animation: _logoScale,
              builder: (_, child) => Transform.scale(
                scale: _logoScale.value,
                child: child,
              ),
              child: Container(
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  color: AppColors.gold,
                  borderRadius: BorderRadius.circular(24),
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.gold.withOpacity(0.35),
                      blurRadius: 24,
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                child: const Center(
                  child: Text(
                    'M',
                    style: TextStyle(
                      fontSize: 48,
                      fontWeight: FontWeight.w900,
                      color: Colors.white,
                      fontFamily: 'Sora',
                      height: 1,
                    ),
                  ),
                ),
              ),
            ),

            const SizedBox(height: 20),

            // ── Arabic wordmark "مزادك" ────────────────────────────
            FadeTransition(
              opacity: _wordmarkOpacity,
              child: const Text(
                'مزادك',
                style: TextStyle(
                  fontSize: 36,
                  fontWeight: FontWeight.w800,
                  color: Colors.white,
                  letterSpacing: 1.5,
                  height: 1,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
