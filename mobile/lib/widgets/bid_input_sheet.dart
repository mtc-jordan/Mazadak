import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/l10n/arabic_numerals.dart';
import '../core/theme/animations.dart';
import '../core/theme/colors.dart';
import '../core/theme/haptics.dart';
import '../core/theme/spacing.dart';

/// Spring curve: cubic-bezier(0, 0.8, 0.3, 1).
const _springCurve = Cubic(0, 0.8, 0.3, 1);

/// Standalone bid input sheet called via [BidInputSheet.show].
///
/// Features:
/// - DraggableScrollableSheet with spring entry + navy overlay
/// - Listing header (thumbnail + title + current price)
/// - Per-digit animated amount display with +/- steppers (long-press repeat)
/// - Quick-add chips (+25, +50, +100, +200) with scale spring
/// - Proxy bid toggle with AnimatedSize max bid input
/// - Validation shake ±6px, 3 cycles
/// - Confirm button: idle→loading→success/error state machine
/// - Velocity-based dismiss
class BidInputSheet extends StatefulWidget {
  const BidInputSheet({
    super.key,
    required this.currentPrice,
    required this.minIncrement,
    required this.currency,
    required this.listingTitle,
    required this.listingImageUrl,
    required this.onConfirm,
  });

  final double currentPrice;
  final double minIncrement;
  final String currency;
  final String listingTitle;
  final String listingImageUrl;
  final Future<bool> Function(double amount, {bool isProxy}) onConfirm;

  /// Show with custom spring route + navy overlay.
  static Future<void> show({
    required BuildContext context,
    required double currentPrice,
    required double minIncrement,
    required String currency,
    required String listingTitle,
    required String listingImageUrl,
    required Future<bool> Function(double amount, {bool isProxy}) onConfirm,
  }) {
    return Navigator.of(context).push(_BidSheetRoute(
      builder: (_) => BidInputSheet(
        currentPrice: currentPrice,
        minIncrement: minIncrement,
        currency: currency,
        listingTitle: listingTitle,
        listingImageUrl: listingImageUrl,
        onConfirm: onConfirm,
      ),
    ));
  }

  @override
  State<BidInputSheet> createState() => _BidInputSheetState();
}

enum _ConfirmState { idle, loading, success, error }

class _BidInputSheetState extends State<BidInputSheet>
    with TickerProviderStateMixin {
  late double _bidAmount;
  bool _isProxy = false;
  double? _maxProxyAmount;
  _ConfirmState _confirmState = _ConfirmState.idle;
  String? _errorText;
  Timer? _longPressTimer;

  // ── Shake ±6px, 3 cycles, 300ms ────────────────────────────────
  late final AnimationController _shakeController;
  late final Animation<double> _shakeOffset;

  // ── Confirm button color morph ──────────────────────────────────
  late final AnimationController _colorController;
  late Animation<Color?> _confirmColor;

  // ── Success checkmark draw ──────────────────────────────────────
  late final AnimationController _checkController;

  // ── Confirm button shake (error) ────────────────────────────────
  late final AnimationController _btnShakeController;
  late final Animation<double> _btnShakeOffset;

  double get _minBid => widget.currentPrice + widget.minIncrement;

  static const _quickAmounts = [25.0, 50.0, 100.0, 200.0];

  @override
  void initState() {
    super.initState();
    _bidAmount = _minBid;

    _shakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _shakeOffset = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: -6), weight: 1),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: 0), weight: 1),
    ]).animate(
        CurvedAnimation(parent: _shakeController, curve: Curves.easeInOut));

    _colorController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _confirmColor = ColorTween(
      begin: AppColors.navy,
      end: AppColors.emerald,
    ).animate(
        CurvedAnimation(parent: _colorController, curve: Curves.easeOut));

    _checkController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    _btnShakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _btnShakeOffset = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: -6), weight: 1),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 0), weight: 1),
    ]).animate(CurvedAnimation(
        parent: _btnShakeController, curve: Curves.easeInOut));
  }

  @override
  void dispose() {
    _longPressTimer?.cancel();
    _shakeController.dispose();
    _colorController.dispose();
    _checkController.dispose();
    _btnShakeController.dispose();
    super.dispose();
  }

  // ── Amount adjustment ───────────────────────────────────────────

  void _adjustBid(double delta) {
    final next = _bidAmount + delta;
    if (next < _minBid) {
      _shakeController.forward(from: 0);
      HapticFeedback.lightImpact();
      setState(() => _errorText = 'Minimum bid is '
          '${ArabicNumerals.formatCurrencyEn(_minBid, widget.currency)}');
      return;
    }
    setState(() {
      _bidAmount = next;
      _errorText = null;
    });
  }

  void _startLongPress(double delta) {
    _adjustBid(delta);
    _longPressTimer = Timer.periodic(const Duration(milliseconds: 100), (_) {
      _adjustBid(delta);
    });
  }

  void _stopLongPress() {
    _longPressTimer?.cancel();
    _longPressTimer = null;
  }

  // ── Confirm ─────────────────────────────────────────────────────

  Future<void> _onConfirm() async {
    if (_confirmState != _ConfirmState.idle) return;

    if (_bidAmount < _minBid) {
      _shakeController.forward(from: 0);
      HapticFeedback.lightImpact();
      return;
    }

    // Proxy validation
    if (_isProxy && _maxProxyAmount != null && _maxProxyAmount! < _bidAmount) {
      setState(() => _errorText = 'Your proxy max is lower than your bid');
      _shakeController.forward(from: 0);
      return;
    }

    HapticFeedback.lightImpact();
    setState(() {
      _confirmState = _ConfirmState.loading;
      _errorText = null;
    });

    final success = await widget.onConfirm(_bidAmount, isProxy: _isProxy);

    if (!mounted) return;

    if (success) {
      setState(() => _confirmState = _ConfirmState.success);
      _colorController.forward();
      _checkController.forward();
      AppHaptics.bidConfirmed();

      await Future.delayed(const Duration(milliseconds: 1500));
      if (mounted) Navigator.of(context).pop();
    } else {
      setState(() => _confirmState = _ConfirmState.error);
      _confirmColor = ColorTween(
        begin: AppColors.navy,
        end: AppColors.ember,
      ).animate(
          CurvedAnimation(parent: _colorController, curve: Curves.easeOut));
      _colorController.forward(from: 0);
      _btnShakeController.forward(from: 0);
      AppHaptics.error();

      await Future.delayed(const Duration(milliseconds: 1500));
      if (mounted) {
        _colorController.reverse();
        setState(() => _confirmState = _ConfirmState.idle);
      }
    }
  }

  // ── Build ───────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final keyboardInset = MediaQuery.of(context).viewInsets.bottom;

    return NotificationListener<DraggableScrollableNotification>(
      onNotification: (notification) {
        // Velocity-based dismiss: fast flick downward closes sheet
        if (notification.extent < 0.35) {
          Navigator.of(context).pop();
          return true;
        }
        return false;
      },
      child: DraggableScrollableSheet(
      initialChildSize: 0.52,
      minChildSize: 0.3,
      maxChildSize: 0.75,
      snap: true,
      snapSizes: const [0.52],
      builder: (context, scrollController) {
        return Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: ListView(
            controller: scrollController,
            padding: EdgeInsets.fromLTRB(24, 12, 24, keyboardInset + 24),
            children: [
              // ── Handle bar ─────────────────────────────────────
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.cream,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // ── Header: title + listing row ────────────────────
              const Text(
                'Place your bid · ضع مزايدتك',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 14),

              // Listing info row
              Row(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(8),
                    child: SizedBox(
                      width: 40,
                      height: 40,
                      child: CachedNetworkImage(
                        imageUrl: widget.listingImageUrl,
                        fit: BoxFit.cover,
                        placeholder: (_, __) =>
                            Container(color: AppColors.sand),
                        errorWidget: (_, __, ___) =>
                            Container(color: AppColors.sand),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      widget.listingTitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: AppColors.ink,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  Text(
                    ArabicNumerals.formatCurrencyEn(
                      widget.currentPrice,
                      widget.currency,
                    ),
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 14,
                      fontWeight: FontWeight.w800,
                      color: AppColors.navy,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),

              // ── Amount display + steppers ───────────────────────
              AnimatedBuilder(
                animation: _shakeController,
                builder: (_, child) => Transform.translate(
                  offset: Offset(
                    _shakeController.isAnimating ? _shakeOffset.value : 0,
                    0,
                  ),
                  child: child,
                ),
                child: Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 14),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(
                      color: _errorText != null
                          ? AppColors.ember
                          : AppColors.sand,
                      width: _errorText != null ? 1.5 : 1,
                    ),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      // Minus stepper
                      _StepperBtn(
                        icon: Icons.remove,
                        enabled: _bidAmount > _minBid,
                        onTap: () =>
                            _adjustBid(-widget.minIncrement),
                        onLongPressStart: () =>
                            _startLongPress(-widget.minIncrement),
                        onLongPressEnd: _stopLongPress,
                      ),
                      const SizedBox(width: 16),

                      // Animated amount
                      Flexible(
                        child: _AnimatedAmount(
                          amount: _bidAmount,
                          currency: widget.currency,
                        ),
                      ),
                      const SizedBox(width: 16),

                      // Plus stepper
                      _StepperBtn(
                        icon: Icons.add,
                        enabled: true,
                        onTap: () =>
                            _adjustBid(widget.minIncrement),
                        onLongPressStart: () =>
                            _startLongPress(widget.minIncrement),
                        onLongPressEnd: _stopLongPress,
                      ),
                    ],
                  ),
                ),
              ),

              // Error / min increment text
              const SizedBox(height: 6),
              if (_errorText != null)
                _SlideInError(text: _errorText!)
              else
                Center(
                  child: Text(
                    'Min next bid: '
                    '${ArabicNumerals.formatCurrencyEn(_minBid, widget.currency)} '
                    '(+${ArabicNumerals.formatCurrencyEn(widget.minIncrement, widget.currency)})',
                    style: const TextStyle(
                      fontSize: 10,
                      color: AppColors.mist,
                    ),
                  ),
                ),
              const SizedBox(height: 18),

              // ── Quick-add chips ────────────────────────────────
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: _quickAmounts.map((amt) {
                  return Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: _QuickChip(
                      amount: amt,
                      onTap: () => _adjustBid(amt),
                    ),
                  );
                }).toList(),
              ),
              const SizedBox(height: 18),

              // ── Proxy bid toggle ───────────────────────────────
              _ProxyToggle(
                isProxy: _isProxy,
                onToggle: () => setState(() {
                  _isProxy = !_isProxy;
                  if (!_isProxy) _maxProxyAmount = null;
                }),
                maxAmount: _maxProxyAmount,
                onMaxChanged: (v) =>
                    setState(() => _maxProxyAmount = v),
                bidAmount: _bidAmount,
                currency: widget.currency,
              ),
              const SizedBox(height: 20),

              // ── Confirm button ─────────────────────────────────
              AnimatedBuilder(
                animation: Listenable.merge(
                    [_colorController, _btnShakeController]),
                builder: (_, child) {
                  final dx = _btnShakeController.isAnimating
                      ? _btnShakeOffset.value
                      : 0.0;
                  return Transform.translate(
                    offset: Offset(dx, 0),
                    child: child,
                  );
                },
                child: SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: AnimatedBuilder(
                    animation: _colorController,
                    builder: (_, __) {
                      final Color bg;
                      if (_confirmState == _ConfirmState.success ||
                          _confirmState == _ConfirmState.error) {
                        bg = _confirmColor.value ?? AppColors.navy;
                      } else {
                        bg = AppColors.navy;
                      }

                      return ElevatedButton(
                        onPressed: _confirmState == _ConfirmState.idle
                            ? _onConfirm
                            : null,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: bg,
                          disabledBackgroundColor: bg,
                          foregroundColor: Colors.white,
                          disabledForegroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(14),
                          ),
                          elevation: 0,
                          textStyle: const TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 14,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        child: AnimatedSwitcher(
                          duration: const Duration(milliseconds: 200),
                          child: _buildConfirmContent(),
                        ),
                      );
                    },
                  ),
                ),
              ),
            ],
          ),
        );
      },
    ),
    );
  }

  Widget _buildConfirmContent() {
    switch (_confirmState) {
      case _ConfirmState.idle:
        return const Text(
          'Place bid · زايد الآن',
          key: ValueKey('idle'),
        );
      case _ConfirmState.loading:
        return const SizedBox(
          key: ValueKey('loading'),
          width: 20,
          height: 20,
          child: CircularProgressIndicator(
            strokeWidth: 2,
            color: Colors.white,
          ),
        );
      case _ConfirmState.success:
        return Row(
          key: const ValueKey('success'),
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 22,
              height: 22,
              child: CustomPaint(
                painter: _CheckPainter(progress: _checkController),
              ),
            ),
            const SizedBox(width: 8),
            const Text('Bid placed! ✓'),
          ],
        );
      case _ConfirmState.error:
        return const Text(
          'Failed — try again',
          key: ValueKey('error'),
        );
    }
  }
}

// ═══════════════════════════════════════════════════════════════════
// Custom route: spring entry + navy overlay
// ═══════════════════════════════════════════════════════════════════

class _BidSheetRoute extends ModalRoute {
  _BidSheetRoute({required this.builder});
  final WidgetBuilder builder;

  @override
  Duration get transitionDuration => const Duration(milliseconds: 400);
  @override
  Duration get reverseTransitionDuration =>
      const Duration(milliseconds: 250);
  @override
  bool get barrierDismissible => true;
  @override
  String? get barrierLabel => 'Dismiss';
  @override
  Color get barrierColor => Colors.transparent;
  @override
  bool get opaque => false;
  @override
  bool get maintainState => true;

  @override
  Widget buildPage(BuildContext context, Animation<double> animation,
      Animation<double> secondaryAnimation) {
    return builder(context);
  }

  @override
  Widget buildTransitions(BuildContext context, Animation<double> animation,
      Animation<double> secondaryAnimation, Widget child) {
    // Navy overlay fades in 200ms
    final overlayFade = Tween(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(
        parent: animation,
        curve: const Interval(0, 0.5, curve: Curves.easeOut),
      ),
    );

    // Sheet from y+100% with spring overshoot
    final slideUp = Tween<Offset>(
      begin: const Offset(0, 1),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: animation,
      curve: _springCurve,
      reverseCurve: Curves.easeIn,
    ));

    return Stack(
      children: [
        FadeTransition(
          opacity: overlayFade,
          child: GestureDetector(
            onTap: () => Navigator.of(context).pop(),
            child: Container(
              color: AppColors.navy.withOpacity(0.6),
            ),
          ),
        ),
        SlideTransition(
          position: slideUp,
          child: Align(
            alignment: Alignment.bottomCenter,
            child: child,
          ),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Animated per-digit amount display
// ═══════════════════════════════════════════════════════════════════

class _AnimatedAmount extends StatelessWidget {
  const _AnimatedAmount({required this.amount, required this.currency});
  final double amount;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final text = ArabicNumerals.formatCurrencyEn(amount, currency);
    return FittedBox(
      fit: BoxFit.scaleDown,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: text.split('').map((char) {
          return AnimatedSwitcher(
            duration: const Duration(milliseconds: 200),
            transitionBuilder: (child, anim) {
              final slide = Tween<Offset>(
                begin: const Offset(0, 0.5),
                end: Offset.zero,
              ).animate(CurvedAnimation(
                parent: anim,
                curve: Curves.easeOutCubic,
              ));
              return FadeTransition(
                opacity: anim,
                child: SlideTransition(
                  position: slide,
                  child: child,
                ),
              );
            },
            child: Text(
              char,
              key: ValueKey('$char-${text.indexOf(char)}-$amount'),
              style: const TextStyle(
                fontFamily: 'Sora',
                fontSize: 28,
                fontWeight: FontWeight.w800,
                color: AppColors.navy,
                height: 1,
              ),
            ),
          );
        }).toList(),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Stepper button with long-press repeat
// ═══════════════════════════════════════════════════════════════════

class _StepperBtn extends StatelessWidget {
  const _StepperBtn({
    required this.icon,
    required this.enabled,
    required this.onTap,
    required this.onLongPressStart,
    required this.onLongPressEnd,
  });

  final IconData icon;
  final bool enabled;
  final VoidCallback onTap;
  final VoidCallback onLongPressStart;
  final VoidCallback onLongPressEnd;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: enabled ? onTap : null,
      onLongPressStart: enabled ? (_) => onLongPressStart() : null,
      onLongPressEnd: enabled ? (_) => onLongPressEnd() : null,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 150),
        opacity: enabled ? 1.0 : 0.3,
        child: Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.sand, width: 1.5),
          ),
          child: Icon(icon, color: AppColors.navy, size: 22),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Quick-add chip with scale spring
// ═══════════════════════════════════════════════════════════════════

class _QuickChip extends StatefulWidget {
  const _QuickChip({required this.amount, required this.onTap});
  final double amount;
  final VoidCallback onTap;

  @override
  State<_QuickChip> createState() => _QuickChipState();
}

class _QuickChipState extends State<_QuickChip>
    with SingleTickerProviderStateMixin {
  late final AnimationController _scale;

  @override
  void initState() {
    super.initState();
    _scale = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 100),
      reverseDuration: const Duration(milliseconds: 200),
      lowerBound: 1.0,
      upperBound: 1.12,
    );
  }

  @override
  void dispose() {
    _scale.dispose();
    super.dispose();
  }

  void _onTap() {
    _scale.forward().then((_) => _scale.reverse());
    HapticFeedback.selectionClick();
    widget.onTap();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _scale,
      builder: (_, child) => Transform.scale(
        scale: _scale.value,
        child: child,
      ),
      child: GestureDetector(
        onTap: _onTap,
        child: Container(
          height: 34,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: AppColors.cream,
            borderRadius: BorderRadius.circular(8),
          ),
          alignment: Alignment.center,
          child: Text(
            '+${widget.amount.toInt()}',
            style: const TextStyle(
              fontFamily: 'Sora',
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppColors.gold,
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Proxy bid toggle
// ═══════════════════════════════════════════════════════════════════

class _ProxyToggle extends StatelessWidget {
  const _ProxyToggle({
    required this.isProxy,
    required this.onToggle,
    required this.maxAmount,
    required this.onMaxChanged,
    required this.bidAmount,
    required this.currency,
  });

  final bool isProxy;
  final VoidCallback onToggle;
  final double? maxAmount;
  final ValueChanged<double?> onMaxChanged;
  final double bidAmount;
  final String currency;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: Row(
                children: [
                  const Text(
                    'Proxy bid · مزايدة وكيل',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Tooltip(
                    message:
                        "We'll automatically bid on your behalf up to your maximum",
                    child: Icon(
                      Icons.info_outline_rounded,
                      size: 16,
                      color: AppColors.mist,
                    ),
                  ),
                ],
              ),
            ),
            Switch.adaptive(
              value: isProxy,
              activeColor: AppColors.emerald,
              onChanged: (_) => onToggle(),
            ),
          ],
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOutCubic,
          child: isProxy
              ? Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      TextField(
                        keyboardType: const TextInputType.numberWithOptions(
                            decimal: true),
                        textDirection: TextDirection.ltr,
                        style: const TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          color: AppColors.navy,
                        ),
                        decoration: InputDecoration(
                          hintText: 'Set maximum',
                          hintStyle: const TextStyle(
                            fontSize: 14,
                            color: AppColors.mist,
                          ),
                          isDense: true,
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 14,
                            vertical: 12,
                          ),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                            borderSide:
                                const BorderSide(color: AppColors.sand),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(12),
                            borderSide:
                                const BorderSide(color: AppColors.navy),
                          ),
                        ),
                        onChanged: (v) {
                          onMaxChanged(double.tryParse(v));
                        },
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        "We'll bid on your behalf up to this amount",
                        style: TextStyle(fontSize: 10, color: AppColors.mist),
                      ),
                    ],
                  ),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Slide-in error text
// ═══════════════════════════════════════════════════════════════════

class _SlideInError extends StatefulWidget {
  const _SlideInError({required this.text});
  final String text;

  @override
  State<_SlideInError> createState() => _SlideInErrorState();
}

class _SlideInErrorState extends State<_SlideInError>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 200),
    )..forward();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SlideTransition(
      position: Tween<Offset>(
        begin: const Offset(0, -0.5),
        end: Offset.zero,
      ).animate(CurvedAnimation(parent: _ctrl, curve: Curves.easeOutCubic)),
      child: FadeTransition(
        opacity: _ctrl,
        child: Center(
          child: Text(
            widget.text,
            style: const TextStyle(
              fontSize: 11,
              color: AppColors.ember,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Checkmark painter (animated draw)
// ═══════════════════════════════════════════════════════════════════

class _CheckPainter extends CustomPainter {
  _CheckPainter({required this.progress}) : super(repaint: progress);
  final Animation<double> progress;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.5
      ..strokeCap = StrokeCap.round;

    final path = Path()
      ..moveTo(size.width * 0.2, size.height * 0.5)
      ..lineTo(size.width * 0.42, size.height * 0.72)
      ..lineTo(size.width * 0.8, size.height * 0.28);

    final metric = path.computeMetrics().first;
    final drawn = metric.extractPath(0, metric.length * progress.value);
    canvas.drawPath(drawn, paint);
  }

  @override
  bool shouldRepaint(_CheckPainter old) => true;
}
