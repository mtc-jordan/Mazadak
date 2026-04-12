import 'package:flutter/material.dart';
import 'package:mzadak/l10n/app_localizations.dart';

import '../../../core/theme/animations.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// 5-step escrow progress tracker with staggered entry animations.
///
/// Animation spec:
/// - Steps animate in sequence: each step node scales in with 80ms offset
/// - Active step has continuous gentle pulse (1.0→1.08, 1.5s loop)
/// - Connecting line draws from start to end when step completes
///
/// SDD §7.2:
/// - Completed steps: emerald with checkmark
/// - Active step: navy with animated icon + pulse
/// - Pending steps: grey/mist
class EscrowProgressTracker extends StatefulWidget {
  const EscrowProgressTracker({
    super.key,
    required this.currentStep,
  });

  /// 0-based step index (0=paid, 1=shipped, 2=in-transit, 3=delivered, 4=released).
  final int currentStep;

  @override
  State<EscrowProgressTracker> createState() => _EscrowProgressTrackerState();
}

class _EscrowProgressTrackerState extends State<EscrowProgressTracker>
    with TickerProviderStateMixin {
  static List<_StepInfo> _steps(BuildContext context) => [
    _StepInfo(icon: Icons.payment_rounded, label: S.of(context).paymentStep),
    _StepInfo(icon: Icons.local_shipping_rounded, label: S.of(context).shippingStep),
    _StepInfo(icon: Icons.flight_rounded, label: S.of(context).inTransitStep),
    _StepInfo(icon: Icons.inventory_2_rounded, label: S.of(context).deliveryStep),
    _StepInfo(icon: Icons.check_circle_rounded, label: S.of(context).releaseStep),
  ];

  // ── Staggered scale-in for each step node ──────────────────────
  final List<AnimationController> _scaleControllers = [];
  final List<Animation<double>> _scaleAnimations = [];

  // ── Active step pulse ──────────────────────────────────────────
  AnimationController? _pulseController;
  Animation<double>? _pulseAnimation;

  // ── Connecting line draw progress ──────────────────────────────
  final List<AnimationController> _lineControllers = [];
  final List<Animation<double>> _lineAnimations = [];

  @override
  void initState() {
    super.initState();
    _buildAnimations();
    _startStaggeredEntry();
  }

  void _buildAnimations() {
    // Scale-in controllers for each of the 5 steps
    for (var i = 0; i < 5; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 300),
      );
      final animation = Tween<double>(begin: 0, end: 1).animate(
        CurvedAnimation(
          parent: controller,
          curve: const Cubic(0, 0.8, 0.3, 1), // spring overshoot
        ),
      );
      _scaleControllers.add(controller);
      _scaleAnimations.add(animation);
    }

    // Line draw controllers for the 4 connectors between steps
    for (var i = 0; i < 4; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 250),
      );
      final animation = Tween<double>(begin: 0, end: 1).animate(
        CurvedAnimation(parent: controller, curve: Curves.easeOut),
      );
      _lineControllers.add(controller);
      _lineAnimations.add(animation);
    }

    // Active step pulse: 1.0 → 1.08 → 1.0, 1.5s loop
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    );
    _pulseAnimation = TweenSequence<double>([
      TweenSequenceItem(
        tween: Tween(begin: 1.0, end: 1.08)
            .chain(CurveTween(curve: Curves.easeOut)),
        weight: 50,
      ),
      TweenSequenceItem(
        tween: Tween(begin: 1.08, end: 1.0)
            .chain(CurveTween(curve: Curves.easeIn)),
        weight: 50,
      ),
    ]).animate(_pulseController!);
    _pulseController!.repeat();
  }

  /// Stagger: 80ms offset per step node, then draw completed lines.
  Future<void> _startStaggeredEntry() async {
    for (var i = 0; i < 5; i++) {
      if (!mounted) return;
      _scaleControllers[i].forward();

      // After each step scales in, draw the preceding line if completed
      if (i > 0 && (i - 1) < widget.currentStep) {
        _lineControllers[i - 1].forward();
      }

      if (i < 4) {
        await Future.delayed(const Duration(milliseconds: 80));
      }
    }
  }

  @override
  void didUpdateWidget(EscrowProgressTracker old) {
    super.didUpdateWidget(old);

    // If step advanced, animate the newly completed line
    if (widget.currentStep > old.currentStep) {
      for (var i = old.currentStep; i < widget.currentStep; i++) {
        if (i < _lineControllers.length) {
          _lineControllers[i].forward();
        }
      }
    }
  }

  @override
  void dispose() {
    for (final c in _scaleControllers) {
      c.dispose();
    }
    for (final c in _lineControllers) {
      c.dispose();
    }
    _pulseController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final steps = _steps(context);
    return Padding(
      padding: AppSpacing.horizontalMd,
      child: Row(
        children: List.generate(steps.length * 2 - 1, (i) {
          if (i.isOdd) {
            // Connector line between steps
            final lineIndex = i ~/ 2;
            final completed = lineIndex < widget.currentStep;

            return Expanded(
              child: AnimatedBuilder(
                animation: _lineAnimations[lineIndex],
                builder: (_, __) {
                  return CustomPaint(
                    painter: _LineDrawPainter(
                      progress: _lineAnimations[lineIndex].value,
                      completed: completed,
                      isRtl: Directionality.of(context) == TextDirection.rtl,
                    ),
                    child: const SizedBox(height: 2),
                  );
                },
              ),
            );
          }

          final stepIndex = i ~/ 2;
          final step = steps[stepIndex];
          final isCompleted = stepIndex < widget.currentStep;
          final isActive = stepIndex == widget.currentStep;

          return _buildStepNode(step, stepIndex, isCompleted, isActive);
        }),
      ),
    );
  }

  Widget _buildStepNode(
    _StepInfo step,
    int index,
    bool isCompleted,
    bool isActive,
  ) {
    final Color bgColor;
    final Color iconColor;
    final IconData icon;

    if (isCompleted) {
      bgColor = AppColors.emerald;
      iconColor = Colors.white;
      icon = Icons.check_rounded;
    } else if (isActive) {
      bgColor = AppColors.navy;
      iconColor = Colors.white;
      icon = Icons.circle; // white dot
    } else {
      bgColor = AppColors.sand;
      iconColor = AppColors.mist;
      icon = step.icon;
    }

    // Scale-in animation wrapper
    Widget node = ScaleTransition(
      scale: _scaleAnimations[index],
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          AnimatedContainer(
            duration: AppAnimations.state,
            curve: AppAnimations.enterCurve,
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: bgColor,
              shape: BoxShape.circle,
              boxShadow: isActive
                  ? [
                      BoxShadow(
                        color: AppColors.navy.withOpacity(0.3),
                        blurRadius: 8,
                        offset: const Offset(0, 2),
                      ),
                    ]
                  : null,
            ),
            child: Icon(icon, color: iconColor, size: isActive ? 10 : 20),
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            step.label,
            style: TextStyle(
              fontSize: 10,
              fontWeight: isActive ? FontWeight.w600 : FontWeight.w400,
              color: isCompleted
                  ? AppColors.emerald
                  : isActive
                      ? AppColors.navy
                      : AppColors.mist,
            ),
          ),
        ],
      ),
    );

    // Wrap active step with continuous pulse
    if (isActive && _pulseAnimation != null) {
      node = AnimatedBuilder(
        animation: _pulseAnimation!,
        builder: (_, child) => Transform.scale(
          scale: _pulseAnimation!.value,
          child: child,
        ),
        child: node,
      );
    }

    return node;
  }
}

class _StepInfo {
  const _StepInfo({required this.icon, required this.label});
  final IconData icon;
  final String label;
}

/// Paints a connecting line that draws from start to end (L→R in LTR, R→L in RTL).
class _LineDrawPainter extends CustomPainter {
  _LineDrawPainter({
    required this.progress,
    required this.completed,
    required this.isRtl,
  });

  final double progress;
  final bool completed;
  final bool isRtl;

  @override
  void paint(Canvas canvas, Size size) {
    final bgPaint = Paint()
      ..color = AppColors.sand
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;

    final fgPaint = Paint()
      ..color = AppColors.emerald
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;

    final y = size.height / 2;

    // Background line (full width, always visible)
    canvas.drawLine(Offset(0, y), Offset(size.width, y), bgPaint);

    // Foreground line (draws based on progress)
    if (completed && progress > 0) {
      final drawWidth = size.width * progress;
      if (isRtl) {
        // Draw from right to left
        canvas.drawLine(
          Offset(size.width, y),
          Offset(size.width - drawWidth, y),
          fgPaint,
        );
      } else {
        // Draw from left to right
        canvas.drawLine(
          Offset(0, y),
          Offset(drawWidth, y),
          fgPaint,
        );
      }
    }
  }

  @override
  bool shouldRepaint(_LineDrawPainter old) =>
      progress != old.progress || completed != old.completed;
}
