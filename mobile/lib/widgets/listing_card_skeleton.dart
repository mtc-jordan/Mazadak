import 'package:flutter/material.dart';
import 'package:shimmer/shimmer.dart';

import '../core/theme/colors.dart';
import '../core/theme/spacing.dart';

/// Shimmer skeleton matching exact ListingCard dimensions.
///
/// Used during initial load and pagination loading states.
/// Matches: 16:9 image, 12px corners, title + price + bid count lines.
class ListingCardSkeleton extends StatelessWidget {
  const ListingCardSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: AppColors.sand,
      highlightColor: AppColors.cream,
      child: Container(
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.sand, width: 1),
        ),
        clipBehavior: Clip.antiAlias,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Image placeholder (16:9) with pulsing MZADAK logo
            AspectRatio(
              aspectRatio: 16 / 9,
              child: Container(
                color: Colors.white,
                child: const Center(
                  child: _PulsingLogo(),
                ),
              ),
            ),

            // Info section
            Padding(
              padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Title line 1
                  Container(
                    width: double.infinity,
                    height: 14,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: AppSpacing.radiusSm,
                    ),
                  ),
                  const SizedBox(height: 6),

                  // Title line 2 (shorter)
                  Container(
                    width: 140,
                    height: 14,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: AppSpacing.radiusSm,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),

                  // Price
                  Container(
                    width: 100,
                    height: 16,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: AppSpacing.radiusSm,
                    ),
                  ),
                  const SizedBox(height: 6),

                  // Bid count
                  Container(
                    width: 60,
                    height: 11,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: AppSpacing.radiusSm,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Pulsing MZADAK "م" logo for skeleton image placeholders.
///
/// Scales between 0.85→1.0 with a 1.2s infinite loop, giving loading
/// states a branded feel instead of a blank shimmer rectangle.
class _PulsingLogo extends StatefulWidget {
  const _PulsingLogo();

  @override
  State<_PulsingLogo> createState() => _PulsingLogoState();
}

class _PulsingLogoState extends State<_PulsingLogo>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _scale;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _scale = TweenSequence<double>([
      TweenSequenceItem(
        tween: Tween(begin: 0.85, end: 1.0)
            .chain(CurveTween(curve: Curves.easeOut)),
        weight: 50,
      ),
      TweenSequenceItem(
        tween: Tween(begin: 1.0, end: 0.85)
            .chain(CurveTween(curve: Curves.easeIn)),
        weight: 50,
      ),
    ]).animate(_controller);
    _controller.repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _scale,
      builder: (_, child) => Transform.scale(
        scale: _scale.value,
        child: child,
      ),
      child: Text(
        'م',
        style: TextStyle(
          fontSize: 28,
          fontWeight: FontWeight.w900,
          color: AppColors.sand,
          height: 1,
        ),
      ),
    );
  }
}

/// Grid of skeleton cards for loading states.
class ListingGridSkeleton extends StatelessWidget {
  const ListingGridSkeleton({
    super.key,
    this.itemCount = 6,
    this.crossAxisCount = 2,
  });

  final int itemCount;
  final int crossAxisCount;

  @override
  Widget build(BuildContext context) {
    return GridView.builder(
      padding: AppSpacing.allMd,
      physics: const NeverScrollableScrollPhysics(),
      shrinkWrap: true,
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: crossAxisCount,
        mainAxisSpacing: AppSpacing.sm,
        crossAxisSpacing: AppSpacing.sm,
        childAspectRatio: 0.72,
      ),
      itemCount: itemCount,
      itemBuilder: (_, __) => const ListingCardSkeleton(),
    );
  }
}
