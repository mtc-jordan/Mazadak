import 'dart:math' as math;

import 'package:confetti/confetti.dart';
import 'package:flutter/material.dart';

import '../core/theme/colors.dart';

/// Overlay that fires a confetti burst on success states.
///
/// Place this in a [Stack] above your content. Call [ConfettiOverlayState.fire]
/// to trigger a single burst from the top-center.
///
/// Example:
/// ```dart
/// final _confettiKey = GlobalKey<ConfettiOverlayState>();
///
/// Stack(children: [
///   content,
///   ConfettiOverlay(key: _confettiKey),
/// ]);
///
/// // Trigger on success:
/// _confettiKey.currentState?.fire();
/// ```
class ConfettiOverlay extends StatefulWidget {
  const ConfettiOverlay({
    super.key,
    this.blastDirection = -math.pi / 2, // upward
    this.numberOfParticles = 30,
    this.gravity = 0.15,
  });

  /// Blast direction in radians. Default is upward (-pi/2).
  final double blastDirection;

  /// Number of particles per burst.
  final int numberOfParticles;

  /// How quickly particles fall.
  final double gravity;

  @override
  State<ConfettiOverlay> createState() => ConfettiOverlayState();
}

class ConfettiOverlayState extends State<ConfettiOverlay> {
  late ConfettiController _controller;

  @override
  void initState() {
    super.initState();
    _controller = ConfettiController(
      duration: const Duration(milliseconds: 500),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// Triggers a single confetti burst.
  void fire() {
    _controller.play();
  }

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConfettiWidget(
        confettiController: _controller,
        blastDirectionality: BlastDirectionality.explosive,
        numberOfParticles: widget.numberOfParticles,
        gravity: widget.gravity,
        emissionFrequency: 0,
        shouldLoop: false,
        colors: const [
          AppColors.gold,
          AppColors.navy,
          AppColors.emerald,
          AppColors.ember,
          AppColors.cream,
        ],
        minimumSize: const Size(6, 3),
        maximumSize: const Size(12, 6),
      ),
    );
  }
}
