import 'package:flutter/material.dart';

import '../../core/theme/colors.dart';

/// Splash screen with MZADAK logo scale-in animation.
///
/// Logo scales from 0 → 1.0 over 400ms with spring overshoot,
/// then holds briefly before auth check navigates away.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _scaleAnimation;
  late Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    // Scale: 0 → ~1.08 (spring overshoot) → 1.0
    _scaleAnimation = Tween<double>(begin: 0, end: 1.0).animate(
      CurvedAnimation(
        parent: _controller,
        curve: const Cubic(0.0, 0.8, 0.3, 1.0), // spring overshoot
      ),
    );

    _fadeAnimation = CurvedAnimation(
      parent: _controller,
      curve: const Interval(0, 0.6, curve: Curves.easeOut),
    );

    _controller.forward();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.cream,
      body: Center(
        child: AnimatedBuilder(
          animation: _controller,
          builder: (_, child) => Opacity(
            opacity: _fadeAnimation.value,
            child: Transform.scale(
              scale: _scaleAnimation.value,
              child: child,
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Logo mark — "م" in navy circle
              Container(
                width: 88,
                height: 88,
                decoration: const BoxDecoration(
                  color: AppColors.navy,
                  shape: BoxShape.circle,
                ),
                child: const Center(
                  child: Text(
                    'م',
                    style: TextStyle(
                      fontSize: 44,
                      fontWeight: FontWeight.w900,
                      color: AppColors.cream,
                      height: 1,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // Wordmark
              const Text(
                'مزادك',
                style: TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w800,
                  color: AppColors.navy,
                  letterSpacing: 1,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
