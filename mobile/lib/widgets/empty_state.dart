import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../core/theme/colors.dart';
import '../core/theme/spacing.dart';

/// Empty state placeholder with a floating SVG illustration.
///
/// The illustration gently floats up and down (translateY ±4px)
/// in a 3-second infinite loop, giving life to otherwise static screens.
class EmptyState extends StatefulWidget {
  const EmptyState({
    super.key,
    required this.title,
    this.subtitle,
    this.svgAsset,
    this.icon,
    this.action,
  });

  /// Primary message (e.g. "لا توجد مزادات").
  final String title;

  /// Optional secondary message.
  final String? subtitle;

  /// Path to an SVG asset for the illustration.
  final String? svgAsset;

  /// Fallback icon when no SVG is provided.
  final IconData? icon;

  /// Optional action button below the text.
  final Widget? action;

  @override
  State<EmptyState> createState() => _EmptyStateState();
}

class _EmptyStateState extends State<EmptyState>
    with SingleTickerProviderStateMixin {
  late AnimationController _floatController;
  late Animation<double> _floatAnimation;

  @override
  void initState() {
    super.initState();
    _floatController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    );

    // ±4px float using a smooth sine-like tween sequence
    _floatAnimation = TweenSequence<double>([
      TweenSequenceItem(
        tween: Tween<double>(begin: 0, end: -4)
            .chain(CurveTween(curve: Curves.easeInOut)),
        weight: 50,
      ),
      TweenSequenceItem(
        tween: Tween<double>(begin: -4, end: 0)
            .chain(CurveTween(curve: Curves.easeInOut)),
        weight: 50,
      ),
    ]).animate(_floatController);

    _floatController.repeat();
  }

  @override
  void dispose() {
    _floatController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: AppSpacing.allLg,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Floating illustration
            AnimatedBuilder(
              animation: _floatAnimation,
              builder: (_, child) => Transform.translate(
                offset: Offset(0, _floatAnimation.value),
                child: child,
              ),
              child: _buildIllustration(),
            ),
            const SizedBox(height: AppSpacing.lg),

            // Title
            Text(
              widget.title,
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.ink,
              ),
            ),

            // Subtitle
            if (widget.subtitle != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                widget.subtitle!,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                  color: AppColors.mist,
                  height: 1.4,
                ),
              ),
            ],

            // Action button
            if (widget.action != null) ...[
              const SizedBox(height: AppSpacing.lg),
              widget.action!,
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildIllustration() {
    if (widget.svgAsset != null) {
      return SvgPicture.asset(
        widget.svgAsset!,
        width: 120,
        height: 120,
      );
    }

    return Icon(
      widget.icon ?? Icons.inbox_rounded,
      size: 80,
      color: AppColors.sand,
    );
  }
}
