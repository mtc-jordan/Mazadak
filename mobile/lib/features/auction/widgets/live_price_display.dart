import 'package:flutter/material.dart';

import '../../../core/l10n/arabic_numerals.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Amber flash color for price changes.
const _flashColor = Color(0xFFFBE8A0);
const _flashDuration = Duration(milliseconds: 600);

/// Live price display with per-digit AnimatedSwitcher and amber flash.
///
/// SDD §7.2: Price changes trigger a SlideTransition per digit (up = rise)
/// and an amber background flash (#FBE8A0) fading over 600ms via ColorTween.
/// Font: Sora 36sp/700 navy.
class LivePriceDisplay extends StatefulWidget {
  const LivePriceDisplay({
    super.key,
    required this.price,
    required this.currency,
    this.locale = 'ar_JO',
  });

  final double price;
  final String currency;
  final String locale;

  @override
  State<LivePriceDisplay> createState() => _LivePriceDisplayState();
}

class _LivePriceDisplayState extends State<LivePriceDisplay>
    with SingleTickerProviderStateMixin {
  late AnimationController _flashController;
  late Animation<Color?> _flashAnimation;
  double _previousPrice = 0;

  @override
  void initState() {
    super.initState();
    _previousPrice = widget.price;

    _flashController = AnimationController(
      vsync: this,
      duration: _flashDuration,
    );

    _flashAnimation = ColorTween(
      begin: _flashColor,
      end: Colors.transparent,
    ).animate(CurvedAnimation(
      parent: _flashController,
      curve: Curves.easeOut,
    ));
  }

  @override
  void didUpdateWidget(LivePriceDisplay old) {
    super.didUpdateWidget(old);
    if (old.price != widget.price) {
      _previousPrice = old.price;
      _flashController.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _flashController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final formatted = ArabicNumerals.formatCurrency(
      widget.price,
      widget.currency,
      locale: widget.locale,
    );

    final goingUp = widget.price >= _previousPrice;

    return AnimatedBuilder(
      animation: _flashAnimation,
      builder: (context, child) {
        return Container(
          decoration: BoxDecoration(
            color: _flashAnimation.value,
            borderRadius: AppSpacing.radiusMd,
          ),
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.xs,
          ),
          child: child,
        );
      },
      child: Row(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: MainAxisAlignment.center,
        children: formatted.split('').map((char) {
          return _AnimatedDigit(
            char: char,
            goingUp: goingUp,
            key: null, // each digit animates independently via its own state
          );
        }).toList(),
      ),
    );
  }
}

/// Single character that slides in from below (price rise) or above (price drop).
class _AnimatedDigit extends StatelessWidget {
  const _AnimatedDigit({
    super.key,
    required this.char,
    required this.goingUp,
  });

  final String char;
  final bool goingUp;

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 300),
      transitionBuilder: (child, animation) {
        // Slide direction: up when price is rising, down when falling.
        final slideBegin = goingUp ? const Offset(0, 0.5) : const Offset(0, -0.5);

        return SlideTransition(
          position: Tween<Offset>(
            begin: slideBegin,
            end: Offset.zero,
          ).animate(CurvedAnimation(
            parent: animation,
            curve: Curves.easeOutCubic,
          )),
          child: FadeTransition(opacity: animation, child: child),
        );
      },
      child: Text(
        char,
        key: ValueKey<String>(char),
        style: const TextStyle(
          fontSize: 36,
          fontWeight: FontWeight.w700,
          color: AppColors.navy,
          fontFamily: 'Sora',
        ),
      ),
    );
  }
}
