import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/animations.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/haptics.dart';
import '../../core/theme/spacing.dart';

/// Pipeline step definitions matching SDD §3.4.1.
enum _PipelineStep {
  clip(
    label: 'تحليل الصور',
    sublabel: 'CLIP ViT-B/32',
    icon: Icons.image_search_rounded,
    estimatedMs: 800,
  ),
  category(
    label: 'تصنيف المنتج',
    sublabel: 'كشف العلامة التجارية والحالة',
    icon: Icons.category_rounded,
    estimatedMs: 500,
  ),
  gpt(
    label: 'كتابة القائمة',
    sublabel: 'GPT-4o عربي/إنجليزي',
    icon: Icons.auto_awesome_rounded,
    estimatedMs: 3500,
  ),
  price(
    label: 'تقدير السعر',
    sublabel: 'Price Oracle',
    icon: Icons.price_change_rounded,
    estimatedMs: 300,
  );

  const _PipelineStep({
    required this.label,
    required this.sublabel,
    required this.icon,
    required this.estimatedMs,
  });

  final String label;
  final String sublabel;
  final IconData icon;
  final int estimatedMs;
}

/// Snap-to-List AI pipeline screen.
///
/// Shows the AI processing pipeline in real-time:
/// CLIP fires first (0.8s) → category detection → GPT-4o generates
/// bilingual listing → Price Oracle suggests range.
///
/// Each step animates in sequence with visual progress:
/// - Pending: mist icon, no fill
/// - Active: navy with spinning progress ring
/// - Complete: emerald with checkmark, scale bounce
///
/// Total pipeline target: <8s P90 (SDD §3.4.1).
class SnapToListScreen extends ConsumerStatefulWidget {
  const SnapToListScreen({
    super.key,
    required this.imageKeys,
  });

  /// S3 keys of the uploaded photos.
  final List<String> imageKeys;

  @override
  ConsumerState<SnapToListScreen> createState() => _SnapToListScreenState();
}

class _SnapToListScreenState extends ConsumerState<SnapToListScreen>
    with TickerProviderStateMixin {
  int _currentStep = 0;
  bool _complete = false;
  String? _error;

  // Step completion animations (scale bounce on complete)
  final List<AnimationController> _stepControllers = [];
  final List<Animation<double>> _stepScales = [];

  // Active step spinner
  late AnimationController _spinController;

  // Overall progress bar
  late AnimationController _progressController;

  @override
  void initState() {
    super.initState();

    _spinController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    )..repeat();

    _progressController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 500),
    );

    for (var i = 0; i < _PipelineStep.values.length; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 300),
      );
      final scale = TweenSequence<double>([
        TweenSequenceItem(
          tween: Tween(begin: 1.0, end: 1.15),
          weight: 40,
        ),
        TweenSequenceItem(
          tween: Tween(begin: 1.15, end: 1.0)
              .chain(CurveTween(curve: Curves.easeOut)),
          weight: 60,
        ),
      ]).animate(controller);

      _stepControllers.add(controller);
      _stepScales.add(scale);
    }

    // Start the pipeline
    _runPipeline();
  }

  Future<void> _runPipeline() async {
    // In real app, this calls POST /api/ai/snap-to-list and streams
    // progress events. Here we simulate the pipeline timing.
    try {
      for (var i = 0; i < _PipelineStep.values.length; i++) {
        if (!mounted) return;
        setState(() => _currentStep = i);

        // Animate progress bar
        _progressController.animateTo(
          (i + 0.5) / _PipelineStep.values.length,
          duration: Duration(
            milliseconds: _PipelineStep.values[i].estimatedMs ~/ 2,
          ),
          curve: Curves.easeOut,
        );

        // Simulate step processing time
        await Future.delayed(
          Duration(milliseconds: _PipelineStep.values[i].estimatedMs),
        );

        if (!mounted) return;

        // Mark step complete with bounce
        _stepControllers[i].forward();
        HapticFeedback.selectionClick();

        // Progress bar to step end
        _progressController.animateTo(
          (i + 1) / _PipelineStep.values.length,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );

        // Small pause between steps
        if (i < _PipelineStep.values.length - 1) {
          await Future.delayed(const Duration(milliseconds: 200));
        }
      }

      if (!mounted) return;
      setState(() => _complete = true);
      AppHaptics.bidConfirmed(); // success haptic

    } catch (e) {
      if (mounted) {
        setState(() => _error = e.toString());
      }
    }
  }

  @override
  void dispose() {
    _spinController.dispose();
    _progressController.dispose();
    for (final c in _stepControllers) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: AppColors.navy,
        title: const Text(
          'Snap-to-List',
          style: TextStyle(
            fontWeight: FontWeight.w700,
            fontFamily: 'Sora',
          ),
        ),
        centerTitle: true,
      ),
      body: SafeArea(
        child: Padding(
          padding: AppSpacing.allLg,
          child: Column(
            children: [
              const SizedBox(height: AppSpacing.lg),

              // ── Header illustration ──────────────────────────────
              const Icon(
                Icons.auto_awesome_rounded,
                size: 48,
                color: AppColors.navy,
              ),
              const SizedBox(height: AppSpacing.md),
              Text(
                _complete
                    ? 'القائمة جاهزة!'
                    : 'جاري تحليل صورك بالذكاء الاصطناعي...',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                '${widget.imageKeys.length} صور • الهدف أقل من ٦٠ ثانية',
                style: const TextStyle(
                  fontSize: 13,
                  color: AppColors.mist,
                ),
              ),

              const SizedBox(height: AppSpacing.xl),

              // ── Overall progress bar ─────────────────────────────
              AnimatedBuilder(
                animation: _progressController,
                builder: (_, __) => ClipRRect(
                  borderRadius: AppSpacing.radiusFull,
                  child: LinearProgressIndicator(
                    value: _progressController.value,
                    minHeight: 6,
                    backgroundColor: AppColors.sand,
                    valueColor: AlwaysStoppedAnimation(
                      _complete ? AppColors.emerald : AppColors.navy,
                    ),
                  ),
                ),
              ),

              const SizedBox(height: AppSpacing.xxl),

              // ── Pipeline steps ───────────────────────────────────
              Expanded(
                child: ListView.separated(
                  itemCount: _PipelineStep.values.length,
                  separatorBuilder: (_, __) =>
                      const SizedBox(height: AppSpacing.md),
                  itemBuilder: (context, index) {
                    final step = _PipelineStep.values[index];
                    final isComplete = index < _currentStep ||
                        (index == _currentStep && _complete);
                    final isActive =
                        index == _currentStep && !_complete;
                    final isPending = index > _currentStep;

                    return _PipelineStepTile(
                      step: step,
                      isComplete: isComplete,
                      isActive: isActive,
                      isPending: isPending,
                      scaleAnimation: _stepScales[index],
                      spinAnimation: _spinController,
                    );
                  },
                ),
              ),

              // ── Error banner ─────────────────────────────────────
              if (_error != null)
                Container(
                  width: double.infinity,
                  padding: AppSpacing.allSm,
                  decoration: BoxDecoration(
                    color: AppColors.ember.withOpacity(0.1),
                    borderRadius: AppSpacing.radiusMd,
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(
                      fontSize: 13,
                      color: AppColors.ember,
                    ),
                  ),
                ),

              // ── Review button (shown when complete) ──────────────
              if (_complete)
                Padding(
                  padding: const EdgeInsetsDirectional.only(
                      top: AppSpacing.md),
                  child: SizedBox(
                    width: double.infinity,
                    height: 52,
                    child: Material(
                      color: AppColors.gold,
                      borderRadius: AppSpacing.radiusMd,
                      child: InkWell(
                        onTap: () {
                          HapticFeedback.lightImpact();
                          // Navigate to review/edit the AI-generated listing
                          Navigator.of(context).pop();
                        },
                        borderRadius: AppSpacing.radiusMd,
                        child: const Center(
                          child: Text(
                            'مراجعة القائمة',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                              color: Colors.white,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Individual pipeline step tile.
class _PipelineStepTile extends StatelessWidget {
  const _PipelineStepTile({
    required this.step,
    required this.isComplete,
    required this.isActive,
    required this.isPending,
    required this.scaleAnimation,
    required this.spinAnimation,
  });

  final _PipelineStep step;
  final bool isComplete;
  final bool isActive;
  final bool isPending;
  final Animation<double> scaleAnimation;
  final Animation<double> spinAnimation;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: scaleAnimation,
      builder: (_, child) => Transform.scale(
        scale: isComplete ? scaleAnimation.value : 1.0,
        child: child,
      ),
      child: AnimatedContainer(
        duration: AppAnimations.state,
        curve: AppAnimations.enterCurve,
        padding: AppSpacing.allMd,
        decoration: BoxDecoration(
          color: isComplete
              ? AppColors.emerald.withOpacity(0.06)
              : isActive
                  ? Colors.white
                  : AppColors.sand.withOpacity(0.3),
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(
            color: isComplete
                ? AppColors.emerald.withOpacity(0.3)
                : isActive
                    ? AppColors.navy.withOpacity(0.2)
                    : Colors.transparent,
          ),
        ),
        child: Row(
          children: [
            // Step icon / status
            _buildStepIcon(),
            const SizedBox(width: AppSpacing.md),

            // Labels
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    step.label,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: isPending
                          ? AppColors.mist
                          : isComplete
                              ? AppColors.emerald
                              : AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    step.sublabel,
                    style: TextStyle(
                      fontSize: 12,
                      color: isPending
                          ? AppColors.mist.withOpacity(0.6)
                          : AppColors.mist,
                    ),
                  ),
                ],
              ),
            ),

            // Timing
            if (isComplete)
              Text(
                '${(step.estimatedMs / 1000).toStringAsFixed(1)}s',
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.emerald,
                  fontFamily: 'Sora',
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildStepIcon() {
    if (isComplete) {
      return Container(
        width: 40,
        height: 40,
        decoration: const BoxDecoration(
          color: AppColors.emerald,
          shape: BoxShape.circle,
        ),
        child: const Icon(Icons.check_rounded, color: Colors.white, size: 20),
      );
    }

    if (isActive) {
      return SizedBox(
        width: 40,
        height: 40,
        child: Stack(
          alignment: Alignment.center,
          children: [
            // Spinning ring
            AnimatedBuilder(
              animation: spinAnimation,
              builder: (_, child) => Transform.rotate(
                angle: spinAnimation.value * 6.283, // 2π
                child: child,
              ),
              child: SizedBox(
                width: 40,
                height: 40,
                child: CircularProgressIndicator(
                  strokeWidth: 3,
                  value: 0.7,
                  valueColor: const AlwaysStoppedAnimation(AppColors.navy),
                  backgroundColor: AppColors.sand,
                ),
              ),
            ),
            // Icon
            Icon(step.icon, color: AppColors.navy, size: 18),
          ],
        ),
      );
    }

    // Pending
    return Container(
      width: 40,
      height: 40,
      decoration: BoxDecoration(
        color: AppColors.sand,
        shape: BoxShape.circle,
      ),
      child: Icon(step.icon, color: AppColors.mist, size: 20),
    );
  }
}
