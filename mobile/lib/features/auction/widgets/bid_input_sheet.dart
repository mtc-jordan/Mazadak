import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/l10n/arabic_numerals.dart';
import '../../../core/theme/animations.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/haptics.dart';
import '../../../core/theme/spacing.dart';

/// Spring curve: cubic-bezier(0, 0.8, 0.3, 1) — slight overshoot.
const _springCurve = Cubic(0, 0.8, 0.3, 1);
const _entryDuration = Duration(milliseconds: 400);
const _overlayFadeDuration = Duration(milliseconds: 200);
const _optimisticTimeout = Duration(seconds: 3);

/// Bid confirmation state machine.
enum _ConfirmState { idle, loading, success, timeout }

/// Modal bottom sheet for bid input — DraggableScrollableSheet with spring
/// entry, custom stepper, quick-add chips, validation shake, animated
/// confirm button with success/timeout states, and proxy bid toggle.
///
/// Entry: slides up from y+100% with spring physics 400ms.
/// Background: semi-transparent navy overlay fades in 200ms.
/// Dismiss: velocity-based — fast flick closes, slow drag shows resistance.
class BidInputSheet extends StatefulWidget {
  const BidInputSheet({
    super.key,
    required this.currentPrice,
    required this.minIncrement,
    required this.currency,
    required this.onConfirm,
    this.locale = 'ar_JO',
  });

  final double currentPrice;
  final double minIncrement;
  final String currency;
  final void Function(double amount, {bool isProxy}) onConfirm;
  final String locale;

  /// Show the sheet with custom spring animation and navy overlay.
  static Future<void> show({
    required BuildContext context,
    required double currentPrice,
    required double minIncrement,
    required String currency,
    required void Function(double amount, {bool isProxy}) onConfirm,
    String locale = 'ar_JO',
  }) {
    return Navigator.of(context).push(_BidSheetRoute(
      builder: (context) => BidInputSheet(
        currentPrice: currentPrice,
        minIncrement: minIncrement,
        currency: currency,
        onConfirm: onConfirm,
        locale: locale,
      ),
    ));
  }

  @override
  State<BidInputSheet> createState() => _BidInputSheetState();
}

class _BidInputSheetState extends State<BidInputSheet>
    with TickerProviderStateMixin {
  late double _bidAmount;
  bool _isProxy = false;
  double? _maxProxyAmount;
  _ConfirmState _confirmState = _ConfirmState.idle;
  Timer? _timeoutTimer;

  // ── Validation shake ────────────────────────────────────────────
  late AnimationController _shakeController;
  late Animation<double> _shakeOffset;

  // ── Confirm button spring ───────────────────────────────────────
  late AnimationController _confirmScaleController;
  late Animation<double> _confirmScale;

  // ── Success checkmark draw ──────────────────────────────────────
  late AnimationController _checkDrawController;

  // ── Confirm button color morph ──────────────────────────────────
  late AnimationController _colorMorphController;
  late Animation<Color?> _colorMorph;

  double get _minBid => widget.currentPrice + widget.minIncrement;

  /// Quick-add chip amounts.
  static const _quickAddAmounts = [25.0, 50.0, 100.0, 200.0];

  @override
  void initState() {
    super.initState();
    _bidAmount = _minBid;

    // Shake: ±6px, 3 cycles
    _shakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 350),
    );
    _shakeOffset = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: 6), weight: 1),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 0), weight: 1),
    ]).animate(CurvedAnimation(
      parent: _shakeController,
      curve: Curves.easeInOut,
    ));

    // Confirm tap scale
    _confirmScaleController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 100),
      reverseDuration: const Duration(milliseconds: 200),
    );
    _confirmScale = Tween(begin: 1.0, end: 0.97).animate(
      CurvedAnimation(
        parent: _confirmScaleController,
        curve: Curves.easeOut,
        reverseCurve: AppAnimations.springCurve,
      ),
    );

    // Checkmark draw
    _checkDrawController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    // Color morph gold → emerald
    _colorMorphController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _colorMorph = ColorTween(
      begin: AppColors.gold,
      end: AppColors.emerald,
    ).animate(CurvedAnimation(
      parent: _colorMorphController,
      curve: Curves.easeOut,
    ));
  }

  @override
  void dispose() {
    _shakeController.dispose();
    _confirmScaleController.dispose();
    _checkDrawController.dispose();
    _colorMorphController.dispose();
    _timeoutTimer?.cancel();
    super.dispose();
  }

  void _adjustBid(double delta) {
    final newAmount = _bidAmount + delta;
    if (newAmount < _minBid) {
      // Validation shake
      _shakeController.forward(from: 0);
      HapticFeedback.lightImpact();
      return;
    }
    setState(() => _bidAmount = newAmount);
  }

  void _onConfirmTap() async {
    if (_confirmState != _ConfirmState.idle) return;

    // Validate minimum
    if (_bidAmount < _minBid) {
      _shakeController.forward(from: 0);
      HapticFeedback.lightImpact();
      return;
    }

    // Tap animation
    await _confirmScaleController.forward();
    _confirmScaleController.reverse();

    setState(() => _confirmState = _ConfirmState.loading);

    // Fire the bid callback
    widget.onConfirm(_bidAmount, isProxy: _isProxy);

    // Start 3s optimistic timeout
    _timeoutTimer = Timer(_optimisticTimeout, () {
      if (mounted && _confirmState == _ConfirmState.loading) {
        setState(() => _confirmState = _ConfirmState.timeout);
      }
    });

    // Simulate success after a small delay (server confirms via WS,
    // but we show success animation optimistically)
    await Future.delayed(const Duration(milliseconds: 600));
    if (mounted && _confirmState == _ConfirmState.loading) {
      _timeoutTimer?.cancel();
      setState(() => _confirmState = _ConfirmState.success);
      _colorMorphController.forward();
      _checkDrawController.forward();
      AppHaptics.bidConfirmed();

      // Auto-dismiss after showing success
      await Future.delayed(const Duration(milliseconds: 800));
      if (mounted) Navigator.of(context).pop();
    }
  }

  void _toggleProxy() {
    setState(() {
      _isProxy = !_isProxy;
      if (!_isProxy) _maxProxyAmount = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final bottomPadding = MediaQuery.of(context).viewInsets.bottom;

    return DraggableScrollableSheet(
      initialChildSize: 0.55,
      minChildSize: 0.3,
      maxChildSize: 0.75,
      snap: true,
      snapSizes: const [0.55],
      builder: (context, scrollController) {
        return NotificationListener<DraggableScrollableNotification>(
          onNotification: (notification) {
            // Velocity-based dismiss: fast flick below threshold closes
            if (notification.extent < 0.35) {
              Navigator.of(context).pop();
              return true;
            }
            return false;
          },
          child: Container(
            decoration: const BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
            ),
            child: ListView(
              controller: scrollController,
              padding: EdgeInsetsDirectional.only(
                start: AppSpacing.lg,
                end: AppSpacing.lg,
                top: AppSpacing.sm,
                bottom: bottomPadding + AppSpacing.lg,
              ),
              children: [
                // ── Handle bar ───────────────────────────────────
                Center(
                  child: Container(
                    width: 32,
                    height: 4,
                    margin: const EdgeInsetsDirectional.only(
                        bottom: AppSpacing.lg),
                    decoration: BoxDecoration(
                      color: AppColors.mist.withValues(alpha: 0.3),
                      borderRadius: AppSpacing.radiusFull,
                    ),
                  ),
                ),

                // ── Title ────────────────────────────────────────
                const Text(
                  'ضع مزايدتك',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy,
                  ),
                ),
                const SizedBox(height: AppSpacing.xxs),

                // ── Minimum bid info ─────────────────────────────
                Text(
                  'الحد الأدنى: ${ArabicNumerals.formatCurrency(_minBid, widget.currency, locale: widget.locale)}',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 13, color: AppColors.mist),
                ),
                const SizedBox(height: AppSpacing.xl),

                // ── Amount display with +/- steppers ─────────────
                _buildAmountSection(),
                const SizedBox(height: AppSpacing.lg),

                // ── Quick-add chips ──────────────────────────────
                _buildQuickAddChips(),
                const SizedBox(height: AppSpacing.lg),

                // ── Proxy bid toggle ─────────────────────────────
                _buildProxyToggle(),
                const SizedBox(height: AppSpacing.lg),

                // ── Timeout warning banner ───────────────────────
                if (_confirmState == _ConfirmState.timeout)
                  _buildTimeoutBanner(),

                // ── Confirm button ───────────────────────────────
                _buildConfirmButton(),
              ],
            ),
          ),
        );
      },
    );
  }

  // ── Amount section with shake validation ────────────────────────

  Widget _buildAmountSection() {
    return AnimatedBuilder(
      animation: _shakeOffset,
      builder: (context, child) {
        return Transform.translate(
          offset: Offset(
            _shakeController.isAnimating ? _shakeOffset.value : 0,
            0,
          ),
          child: child,
        );
      },
      child: AnimatedContainer(
        duration: AppAnimations.state,
        padding: AppSpacing.allMd,
        decoration: BoxDecoration(
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(
            color: _bidAmount < _minBid ? AppColors.ember : AppColors.sand,
            width: _bidAmount < _minBid ? 2 : 1,
          ),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Minus button
            _StepperButton(
              icon: Icons.remove,
              onTap: _bidAmount > _minBid
                  ? () => _adjustBid(-widget.minIncrement)
                  : null,
            ),
            const SizedBox(width: AppSpacing.lg),

            // Amount display
            Flexible(
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Text(
                  ArabicNumerals.formatCurrency(
                    _bidAmount,
                    widget.currency,
                    locale: widget.locale,
                  ),
                  style: const TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy,
                    fontFamily: 'Sora',
                  ),
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.lg),

            // Plus button
            _StepperButton(
              icon: Icons.add,
              onTap: () => _adjustBid(widget.minIncrement),
            ),
          ],
        ),
      ),
    );
  }

  // ── Quick-add chips with tap scale animation ────────────────────

  Widget _buildQuickAddChips() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: _quickAddAmounts.map((amount) {
        return Padding(
          padding:
              const EdgeInsetsDirectional.symmetric(horizontal: AppSpacing.xxs),
          child: _QuickAddChip(
            amount: amount,
            currency: widget.currency,
            locale: widget.locale,
            onTap: () => _adjustBid(amount),
          ),
        );
      }).toList(),
    );
  }

  // ── Proxy bid toggle with AnimatedSize ──────────────────────────

  Widget _buildProxyToggle() {
    return Column(
      children: [
        InkWell(
          onTap: _toggleProxy,
          borderRadius: AppSpacing.radiusMd,
          child: Padding(
            padding: const EdgeInsetsDirectional.symmetric(
                vertical: AppSpacing.sm),
            child: Row(
              children: [
                AnimatedContainer(
                  duration: AppAnimations.state,
                  width: 44,
                  height: 26,
                  decoration: BoxDecoration(
                    color: _isProxy ? AppColors.navy : AppColors.sand,
                    borderRadius: AppSpacing.radiusFull,
                  ),
                  child: AnimatedAlign(
                    duration: AppAnimations.state,
                    curve: AppAnimations.springCurve,
                    alignment: _isProxy
                        ? AlignmentDirectional.centerEnd
                        : AlignmentDirectional.centerStart,
                    child: Container(
                      width: 22,
                      height: 22,
                      margin: const EdgeInsetsDirectional.all(2),
                      decoration: const BoxDecoration(
                        color: Colors.white,
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                const Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'مزايدة تلقائية (بروكسي)',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                          color: AppColors.ink,
                        ),
                      ),
                      Text(
                        'النظام يزايد تلقائياً حتى الحد الأقصى',
                        style: TextStyle(fontSize: 12, color: AppColors.mist),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),

        // Expandable max proxy input
        AnimatedSize(
          duration: AppAnimations.enter,
          curve: AppAnimations.enterCurve,
          child: _isProxy
              ? Padding(
                  padding:
                      const EdgeInsetsDirectional.only(top: AppSpacing.sm),
                  child: Row(
                    children: [
                      const Text(
                        'الحد الأقصى:',
                        style: TextStyle(
                            fontSize: 13, color: AppColors.mist),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: TextField(
                          keyboardType: const TextInputType.numberWithOptions(
                              decimal: true),
                          textDirection: TextDirection.ltr,
                          style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            fontFamily: 'Sora',
                            color: AppColors.navy,
                          ),
                          decoration: InputDecoration(
                            hintText: ArabicNumerals.formatCurrency(
                              _bidAmount * 2,
                              widget.currency,
                              locale: widget.locale,
                            ),
                            hintTextDirection: TextDirection.ltr,
                            isDense: true,
                            contentPadding:
                                const EdgeInsetsDirectional.symmetric(
                              horizontal: AppSpacing.sm,
                              vertical: AppSpacing.xs,
                            ),
                            border: OutlineInputBorder(
                              borderRadius: AppSpacing.radiusMd,
                              borderSide:
                                  const BorderSide(color: AppColors.sand),
                            ),
                            focusedBorder: OutlineInputBorder(
                              borderRadius: AppSpacing.radiusMd,
                              borderSide:
                                  const BorderSide(color: AppColors.navy),
                            ),
                          ),
                          onChanged: (v) {
                            final parsed = double.tryParse(v);
                            setState(
                                () => _maxProxyAmount = parsed);
                          },
                        ),
                      ),
                    ],
                  ),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }

  // ── Timeout warning banner ──────────────────────────────────────

  Widget _buildTimeoutBanner() {
    return Container(
      margin: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
      padding: AppSpacing.allSm,
      decoration: BoxDecoration(
        color: const Color(0xFFFFF3CD),
        borderRadius: AppSpacing.radiusMd,
        border: Border.all(color: AppColors.gold.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              valueColor:
                  AlwaysStoppedAnimation<Color>(AppColors.gold),
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          const Text(
            'جاري التأكيد...',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w500,
              color: AppColors.gold,
            ),
          ),
        ],
      ),
    );
  }

  // ── Confirm button with state machine ───────────────────────────

  Widget _buildConfirmButton() {
    return AnimatedBuilder(
      animation: Listenable.merge([_confirmScale, _colorMorph]),
      builder: (context, child) {
        return Transform.scale(
          scale: _confirmScale.value,
          child: child,
        );
      },
      child: SizedBox(
        width: double.infinity,
        height: 52,
        child: Material(
          color: _confirmState == _ConfirmState.success
              ? _colorMorph.value
              : (_confirmState == _ConfirmState.idle ||
                      _confirmState == _ConfirmState.timeout)
                  ? AppColors.gold
                  : AppColors.gold,
          borderRadius: AppSpacing.radiusMd,
          child: InkWell(
            onTap: _confirmState == _ConfirmState.idle ? _onConfirmTap : null,
            borderRadius: AppSpacing.radiusMd,
            child: Center(
              child: AnimatedSwitcher(
                duration: AppAnimations.state,
                child: _buildConfirmContent(),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildConfirmContent() {
    switch (_confirmState) {
      case _ConfirmState.idle:
        return Text(
          _isProxy ? 'تأكيد المزايدة التلقائية' : 'تأكيد المزايدة',
          key: const ValueKey('idle'),
          style: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        );

      case _ConfirmState.loading:
        return const SizedBox(
          key: ValueKey('loading'),
          width: 24,
          height: 24,
          child: CircularProgressIndicator(
            strokeWidth: 2.5,
            valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
          ),
        );

      case _ConfirmState.success:
        return SizedBox(
          key: const ValueKey('success'),
          width: 28,
          height: 28,
          child: CustomPaint(
            painter: _CheckmarkPainter(progress: _checkDrawController),
          ),
        );

      case _ConfirmState.timeout:
        return const Text(
          key: ValueKey('timeout'),
          'جاري التأكيد...',
          style: TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w600,
            color: Colors.white,
          ),
        );
    }
  }
}

// ── Custom route with spring entry + navy overlay ─────────────────

class _BidSheetRoute extends ModalRoute {
  _BidSheetRoute({required this.builder});

  final WidgetBuilder builder;

  @override
  Duration get transitionDuration => _entryDuration;

  @override
  Duration get reverseTransitionDuration =>
      const Duration(milliseconds: 250);

  @override
  bool get barrierDismissible => true;

  @override
  String? get barrierLabel => 'Dismiss bid sheet';

  @override
  Color get barrierColor => Colors.transparent; // we paint our own

  @override
  bool get opaque => false;

  @override
  bool get maintainState => true;

  @override
  Widget buildPage(
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
  ) {
    return builder(context);
  }

  @override
  Widget buildTransitions(
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) {
    // Navy overlay fades in 200ms
    final overlayOpacity = Tween(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(
        parent: animation,
        curve: const Interval(0, 0.5, curve: Curves.easeOut),
      ),
    );

    // Sheet slides up from y+60% with spring overshoot (~3%)
    final slideUp = Tween<Offset>(
      begin: const Offset(0, 0.6),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: animation,
      curve: _springCurve,
      reverseCurve: Curves.easeIn,
    ));

    return Stack(
      children: [
        // Semi-transparent navy overlay
        FadeTransition(
          opacity: overlayOpacity,
          child: GestureDetector(
            onTap: () => Navigator.of(context).pop(),
            child: Container(
              color: AppColors.navy.withValues(alpha: 0.55),
            ),
          ),
        ),

        // Sheet
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

// ── Stepper button ────────────────────────────────────────────────

class _StepperButton extends StatelessWidget {
  const _StepperButton({required this.icon, this.onTap});

  final IconData icon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final enabled = onTap != null;
    return Material(
      color: enabled ? AppColors.navy : AppColors.sand,
      borderRadius: AppSpacing.radiusFull,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppSpacing.radiusFull,
        child: SizedBox(
          width: 48,
          height: 48,
          child: Icon(
            icon,
            color: enabled ? Colors.white : AppColors.mist,
            size: 24,
          ),
        ),
      ),
    );
  }
}

// ── Quick-add chip with tap scale animation ───────────────────────

class _QuickAddChip extends StatefulWidget {
  const _QuickAddChip({
    required this.amount,
    required this.currency,
    required this.locale,
    required this.onTap,
  });

  final double amount;
  final String currency;
  final String locale;
  final VoidCallback onTap;

  @override
  State<_QuickAddChip> createState() => _QuickAddChipState();
}

class _QuickAddChipState extends State<_QuickAddChip>
    with SingleTickerProviderStateMixin {
  late AnimationController _scaleController;
  late Animation<double> _scaleAnimation;

  @override
  void initState() {
    super.initState();
    _scaleController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 100),
      reverseDuration: const Duration(milliseconds: 150),
    );
    _scaleAnimation = Tween(begin: 1.0, end: 1.1).animate(
      CurvedAnimation(
        parent: _scaleController,
        curve: Curves.easeOut,
        reverseCurve: AppAnimations.springCurve,
      ),
    );
  }

  @override
  void dispose() {
    _scaleController.dispose();
    super.dispose();
  }

  void _onTap() {
    _scaleController.forward().then((_) {
      _scaleController.reverse();
    });
    HapticFeedback.selectionClick();
    widget.onTap();
  }

  @override
  Widget build(BuildContext context) {
    return ScaleTransition(
      scale: _scaleAnimation,
      child: Material(
        color: AppColors.sand,
        borderRadius: AppSpacing.radiusFull,
        child: InkWell(
          onTap: _onTap,
          borderRadius: AppSpacing.radiusFull,
          child: Padding(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xs,
            ),
            child: Text(
              '+${ArabicNumerals.formatNumber(widget.amount.toInt(), locale: widget.locale)}',
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: AppColors.navy,
                fontFamily: 'Sora',
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ── Checkmark CustomPainter ───────────────────────────────────────

class _CheckmarkPainter extends CustomPainter {
  _CheckmarkPainter({required this.progress}) : super(repaint: progress);

  final Animation<double> progress;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;

    final path = Path();
    // Checkmark path: ✓ shape
    final startX = size.width * 0.2;
    final startY = size.height * 0.5;
    final midX = size.width * 0.42;
    final midY = size.height * 0.72;
    final endX = size.width * 0.8;
    final endY = size.height * 0.28;

    path.moveTo(startX, startY);
    path.lineTo(midX, midY);
    path.lineTo(endX, endY);

    // Animate the path drawing
    final metric = path.computeMetrics().first;
    final drawLength = metric.length * progress.value;
    final extractedPath = metric.extractPath(0, drawLength);

    canvas.drawPath(extractedPath, paint);
  }

  @override
  bool shouldRepaint(_CheckmarkPainter old) => true;
}
