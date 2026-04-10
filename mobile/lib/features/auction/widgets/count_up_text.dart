import 'package:flutter/material.dart';

import '../../../core/l10n/arabic_numerals.dart';
import '../../../core/theme/animations.dart';

/// Count-up animation from 0 → target over 800ms.
///
/// SDD §7.2: Auction room entry animation — price counts up from 0
/// to current value. Uses TweenAnimationBuilder for smooth interpolation.
///
/// [delay] allows staggering multiple count-ups (e.g., price then stats).
class CountUpText extends StatefulWidget {
  const CountUpText({
    super.key,
    required this.value,
    this.currency,
    this.duration = const Duration(milliseconds: 800),
    this.delay = Duration.zero,
    this.style,
    this.locale = 'ar_JO',
  });

  final double value;
  final String? currency;
  final Duration duration;
  final Duration delay;
  final TextStyle? style;
  final String locale;

  @override
  State<CountUpText> createState() => _CountUpTextState();
}

class _CountUpTextState extends State<CountUpText>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: widget.duration,
    );
    _animation = Tween<double>(begin: 0, end: widget.value).animate(
      CurvedAnimation(parent: _controller, curve: AppAnimations.enterCurve),
    );

    if (widget.delay == Duration.zero) {
      _controller.forward();
    } else {
      Future.delayed(widget.delay, () {
        if (mounted) _controller.forward();
      });
    }
  }

  @override
  void didUpdateWidget(CountUpText old) {
    super.didUpdateWidget(old);
    if (old.value != widget.value) {
      _animation = Tween<double>(
        begin: _animation.value,
        end: widget.value,
      ).animate(CurvedAnimation(
        parent: _controller,
        curve: AppAnimations.enterCurve,
      ));
      _controller.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, _) {
        final text = widget.currency != null
            ? ArabicNumerals.formatCurrency(
                _animation.value, widget.currency!,
                locale: widget.locale)
            : ArabicNumerals.formatNumber(
                _animation.value.round(),
                locale: widget.locale);

        return Text(text, style: widget.style);
      },
    );
  }
}

/// Count-up for integer stats (bid count, watchers, etc.).
///
/// All stats use TweenAnimationBuilder per spec.
/// [delay] offsets the animation start for staggered entry orchestration.
class CountUpInt extends StatefulWidget {
  const CountUpInt({
    super.key,
    required this.value,
    this.duration = const Duration(milliseconds: 800),
    this.delay = Duration.zero,
    this.style,
    this.suffix = '',
    this.locale = 'ar_JO',
  });

  final int value;
  final Duration duration;
  final Duration delay;
  final TextStyle? style;
  final String suffix;
  final String locale;

  @override
  State<CountUpInt> createState() => _CountUpIntState();
}

class _CountUpIntState extends State<CountUpInt>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: widget.duration,
    );
    _animation = Tween<double>(begin: 0, end: widget.value.toDouble()).animate(
      CurvedAnimation(parent: _controller, curve: AppAnimations.enterCurve),
    );

    if (widget.delay == Duration.zero) {
      _controller.forward();
    } else {
      Future.delayed(widget.delay, () {
        if (mounted) _controller.forward();
      });
    }
  }

  @override
  void didUpdateWidget(CountUpInt old) {
    super.didUpdateWidget(old);
    if (old.value != widget.value) {
      _animation = Tween<double>(
        begin: _animation.value,
        end: widget.value.toDouble(),
      ).animate(CurvedAnimation(
        parent: _controller,
        curve: AppAnimations.enterCurve,
      ));
      _controller.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _animation,
      builder: (context, _) {
        final text =
            '${ArabicNumerals.formatNumber(_animation.value.round(), locale: widget.locale)}${widget.suffix}';
        return Text(text, style: widget.style);
      },
    );
  }
}
