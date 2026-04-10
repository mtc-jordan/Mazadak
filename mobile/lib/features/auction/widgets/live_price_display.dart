import 'package:flutter/material.dart';

import '../../../core/l10n/arabic_numerals.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Amber flash color for price changes.
const _flashColor = Color(0xFFFBE8A0);
const _flashDuration = Duration(milliseconds: 600);
const _countUpDuration = Duration(milliseconds: 800);

/// Live price display with per-digit AnimatedSwitcher, amber flash,
/// and entry count-up animation.
///
/// SDD §7.2:
/// - On entry: price counts up from 0 → current value over 800ms
/// - Price changes trigger SlideTransition per digit (up = rise)
/// - Amber background flash (#FBE8A0) fading over 600ms via ColorTween
/// - Font: Sora 36sp/700 navy
///
/// Wrap in a Hero widget with [HeroTags.price(id)] on both the
/// listing detail and auction room to get the price hero fly effect.
class LivePriceDisplay extends StatefulWidget {
  const LivePriceDisplay({
    super.key,
    required this.price,
    required this.currency,
    this.locale = 'ar_JO',
    this.heroTag,
    this.animateEntry = true,
  });

  final double price;
  final String currency;
  final String locale;

  /// Optional Hero tag. When set, wraps the display in a Hero.
  final String? heroTag;

  /// When true, counts up from 0 on first build (800ms).
  final bool animateEntry;

  @override
  State<LivePriceDisplay> createState() => _LivePriceDisplayState();
}

class _LivePriceDisplayState extends State<LivePriceDisplay>
    with TickerProviderStateMixin {
  late AnimationController _flashController;
  late Animation<Color?> _flashAnimation;
  double _previousPrice = 0;

  // Entry count-up
  late AnimationController _countUpController;
  late Animation<double> _countUpAnimation;
  bool _entryDone = false;

  @override
  void initState() {
    super.initState();
    _previousPrice = widget.price;

    // Flash controller
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

    // Count-up controller
    _countUpController = AnimationController(
      vsync: this,
      duration: _countUpDuration,
    );
    _countUpAnimation = Tween<double>(
      begin: 0,
      end: widget.price,
    ).animate(CurvedAnimation(
      parent: _countUpController,
      curve: Curves.easeOutCubic,
    ));

    if (widget.animateEntry && widget.price > 0) {
      _countUpController.forward().then((_) {
        if (mounted) setState(() => _entryDone = true);
      });
    } else {
      _entryDone = true;
    }
  }

  @override
  void didUpdateWidget(LivePriceDisplay old) {
    super.didUpdateWidget(old);
    if (old.price != widget.price && _entryDone) {
      _previousPrice = old.price;
      _flashController.forward(from: 0);
    }
    // If price changed during count-up, snap to done and show new price
    if (old.price != widget.price && !_entryDone) {
      _countUpController.stop();
      _entryDone = true;
      _previousPrice = old.price;
      _flashController.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _flashController.dispose();
    _countUpController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    Widget display;

    if (!_entryDone) {
      // Count-up phase: animate from 0 → current price
      display = AnimatedBuilder(
        animation: _countUpAnimation,
        builder: (context, _) {
          final formatted = ArabicNumerals.formatCurrencyEn(
            _countUpAnimation.value,
            widget.currency,
          );
          return _buildPriceRow(formatted);
        },
      );
    } else {
      // Steady state: per-digit AnimatedSwitcher with flash
      final formatted = ArabicNumerals.formatCurrencyEn(
        widget.price,
        widget.currency,
      );
      final goingUp = widget.price >= _previousPrice;

      display = AnimatedBuilder(
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
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.center,
            children: formatted.split('').asMap().entries.map((entry) {
              return _AnimatedDigit(
                  char: entry.value, goingUp: goingUp, index: entry.key);
            }).toList(),
          ),
        ),
      );
    }

    // Wrap in Hero if tag provided (price hero: listing → auction)
    if (widget.heroTag != null) {
      return Hero(
        tag: widget.heroTag!,
        flightShuttleBuilder: _priceHeroShuttle,
        child: Material(
          type: MaterialType.transparency,
          child: display,
        ),
      );
    }

    return display;
  }

  Widget _buildPriceRow(String formatted) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xs,
      ),
      child: Directionality(
        textDirection: TextDirection.ltr,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: MainAxisAlignment.center,
          children: formatted.split('').map((char) {
            return Text(
              char,
              style: const TextStyle(
                fontSize: 36,
                fontWeight: FontWeight.w700,
                color: AppColors.navy,
                fontFamily: 'Sora',
              ),
            );
          }).toList(),
        ),
      ),
    );
  }

  /// Hero flight shuttle: scale up smoothly during the flight.
  static Widget _priceHeroShuttle(
    BuildContext flightContext,
    Animation<double> animation,
    HeroFlightDirection flightDirection,
    BuildContext fromHeroContext,
    BuildContext toHeroContext,
  ) {
    final toWidget = toHeroContext.widget as Hero;
    return ScaleTransition(
      scale: Tween<double>(begin: 0.85, end: 1.0).animate(
        CurvedAnimation(parent: animation, curve: Curves.easeInOutCubic),
      ),
      child: toWidget.child,
    );
  }
}

/// Single character that slides in from below (price rise) or above (price drop).
class _AnimatedDigit extends StatelessWidget {
  const _AnimatedDigit({
    required this.char,
    required this.goingUp,
    this.index = 0,
  });

  final String char;
  final bool goingUp;
  final int index;

  @override
  Widget build(BuildContext context) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 300),
      transitionBuilder: (child, animation) {
        final slideBegin =
            goingUp ? const Offset(0, 0.5) : const Offset(0, -0.5);

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
        key: ValueKey<String>('$char-$index'),
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
