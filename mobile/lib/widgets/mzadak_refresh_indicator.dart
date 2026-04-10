import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../core/theme/colors.dart';
import '../core/theme/spacing.dart';

/// Custom pull-to-refresh that shows a spinning MZADAK "م" logo.
///
/// Uses a [NotificationListener] over the scrollable child to track
/// overscroll, then triggers [onRefresh] and spins the logo until complete.
class MzadakRefreshIndicator extends StatefulWidget {
  const MzadakRefreshIndicator({
    super.key,
    required this.child,
    required this.onRefresh,
  });

  final Widget child;
  final Future<void> Function() onRefresh;

  @override
  State<MzadakRefreshIndicator> createState() =>
      _MzadakRefreshIndicatorState();
}

class _MzadakRefreshIndicatorState extends State<MzadakRefreshIndicator>
    with SingleTickerProviderStateMixin {
  late AnimationController _spinController;
  double _dragOffset = 0;
  bool _refreshing = false;

  static const _triggerDistance = 80.0;
  static const _maxDrag = 120.0;

  @override
  void initState() {
    super.initState();
    _spinController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 800),
    );
  }

  @override
  void dispose() {
    _spinController.dispose();
    super.dispose();
  }

  bool _handleOverscroll(OverscrollNotification notification) {
    if (_refreshing) return false;
    if (notification.overscroll < 0) {
      // Pulling down past the top
      setState(() {
        _dragOffset = (_dragOffset - notification.overscroll)
            .clamp(0.0, _maxDrag);
      });
    }
    return false;
  }

  bool _handleScrollEnd(ScrollEndNotification notification) {
    if (_refreshing) return false;
    if (_dragOffset >= _triggerDistance) {
      _startRefresh();
    } else {
      setState(() => _dragOffset = 0);
    }
    return false;
  }

  bool _handleScrollUpdate(ScrollUpdateNotification notification) {
    if (_refreshing) return false;
    // Reset drag when user scrolls normally
    if (_dragOffset > 0 &&
        notification.scrollDelta != null &&
        notification.scrollDelta! > 0) {
      setState(() {
        _dragOffset = (_dragOffset - notification.scrollDelta!)
            .clamp(0.0, _maxDrag);
      });
    }
    return false;
  }

  Future<void> _startRefresh() async {
    setState(() => _refreshing = true);
    _spinController.repeat();
    try {
      await widget.onRefresh();
    } finally {
      if (mounted) {
        _spinController.stop();
        setState(() {
          _refreshing = false;
          _dragOffset = 0;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final showIndicator = _dragOffset > 0 || _refreshing;
    final displayOffset = _refreshing ? _triggerDistance : _dragOffset;
    final progress = (displayOffset / _triggerDistance).clamp(0.0, 1.0);

    return NotificationListener<ScrollNotification>(
      onNotification: (notification) {
        if (notification is OverscrollNotification) {
          return _handleOverscroll(notification);
        } else if (notification is ScrollEndNotification) {
          return _handleScrollEnd(notification);
        } else if (notification is ScrollUpdateNotification) {
          return _handleScrollUpdate(notification);
        }
        return false;
      },
      child: Stack(
        children: [
          // Push child down during drag
          AnimatedPadding(
            duration: _refreshing
                ? const Duration(milliseconds: 200)
                : Duration.zero,
            padding: EdgeInsets.only(top: displayOffset * 0.5),
            child: widget.child,
          ),

          // Spinning logo header
          if (showIndicator)
            Positioned(
              top: displayOffset * 0.5 - 36,
              left: 0,
              right: 0,
              child: Center(
                child: AnimatedBuilder(
                  animation: _spinController,
                  builder: (_, child) {
                    final spinAngle = _spinController.isAnimating
                        ? _spinController.value * 2 * math.pi
                        : progress * math.pi;
                    return Opacity(
                      opacity: progress,
                      child: Transform.rotate(
                        angle: spinAngle,
                        child: child,
                      ),
                    );
                  },
                  child: Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      shape: BoxShape.circle,
                      boxShadow: [
                        BoxShadow(
                          color: AppColors.navy.withOpacity(0.12),
                          blurRadius: 8,
                          offset: const Offset(0, 2),
                        ),
                      ],
                    ),
                    child: const Center(
                      child: Text(
                        'م',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w900,
                          color: AppColors.navy,
                          height: 1,
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
