import 'package:flutter/material.dart';

import '../../../core/l10n/arabic_numerals.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Modal bottom sheet for bid input with +/- steppers and proxy bid option.
///
/// SDD §7.2 BidInputSheet:
/// - +/- stepper buttons with increment presets
/// - Current minimum bid displayed
/// - Proxy bid toggle option
/// - Confirm button
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

  /// Show the sheet as a modal bottom sheet.
  static Future<void> show({
    required BuildContext context,
    required double currentPrice,
    required double minIncrement,
    required String currency,
    required void Function(double amount, {bool isProxy}) onConfirm,
    String locale = 'ar_JO',
  }) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => BidInputSheet(
        currentPrice: currentPrice,
        minIncrement: minIncrement,
        currency: currency,
        onConfirm: onConfirm,
        locale: locale,
      ),
    );
  }

  @override
  State<BidInputSheet> createState() => _BidInputSheetState();
}

class _BidInputSheetState extends State<BidInputSheet> {
  late double _bidAmount;
  bool _isProxy = false;

  double get _minBid => widget.currentPrice + widget.minIncrement;

  /// Preset increment multipliers.
  List<double> get _presets => [
        widget.minIncrement,
        widget.minIncrement * 2,
        widget.minIncrement * 5,
        widget.minIncrement * 10,
      ];

  @override
  void initState() {
    super.initState();
    _bidAmount = _minBid;
  }

  void _adjustBid(double delta) {
    setState(() {
      _bidAmount = (_bidAmount + delta).clamp(_minBid, double.infinity);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      padding: EdgeInsetsDirectional.only(
        start: AppSpacing.lg,
        end: AppSpacing.lg,
        top: AppSpacing.md,
        bottom: MediaQuery.of(context).viewInsets.bottom + AppSpacing.lg,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // ── Drag handle ──────────────────────────────────────────
          Container(
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: AppColors.sand,
              borderRadius: AppSpacing.radiusFull,
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // ── Title ────────────────────────────────────────────────
          const Text(
            'ضع مزايدتك',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),

          // ── Minimum bid info ─────────────────────────────────────
          Text(
            'الحد الأدنى: ${ArabicNumerals.formatCurrency(_minBid, widget.currency, locale: widget.locale)}',
            style: const TextStyle(fontSize: 13, color: AppColors.mist),
          ),
          const SizedBox(height: AppSpacing.lg),

          // ── Amount display with +/- buttons ──────────────────────
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _StepperButton(
                icon: Icons.remove,
                onTap: _bidAmount > _minBid
                    ? () => _adjustBid(-widget.minIncrement)
                    : null,
              ),
              const SizedBox(width: AppSpacing.lg),
              Text(
                ArabicNumerals.formatCurrency(
                  _bidAmount,
                  widget.currency,
                  locale: widget.locale,
                ),
                style: const TextStyle(
                  fontSize: 32,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                  fontFamily: 'Sora',
                ),
              ),
              const SizedBox(width: AppSpacing.lg),
              _StepperButton(
                icon: Icons.add,
                onTap: () => _adjustBid(widget.minIncrement),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),

          // ── Quick increment presets ──────────────────────────────
          Wrap(
            spacing: AppSpacing.xs,
            children: _presets.map((preset) {
              return ActionChip(
                label: Text(
                  '+${ArabicNumerals.formatCurrency(preset, widget.currency, locale: widget.locale)}',
                  style: const TextStyle(fontSize: 12),
                ),
                onPressed: () => _adjustBid(preset),
                backgroundColor: AppColors.sand,
                side: BorderSide.none,
              );
            }).toList(),
          ),
          const SizedBox(height: AppSpacing.lg),

          // ── Proxy bid toggle ─────────────────────────────────────
          SwitchListTile(
            title: const Text(
              'مزايدة تلقائية (بروكسي)',
              style: TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
            ),
            subtitle: const Text(
              'النظام يزايد تلقائياً حتى الحد الأقصى',
              style: TextStyle(fontSize: 12, color: AppColors.mist),
            ),
            value: _isProxy,
            onChanged: (v) => setState(() => _isProxy = v),
            activeColor: AppColors.navy,
            contentPadding: EdgeInsetsDirectional.zero,
          ),
          const SizedBox(height: AppSpacing.md),

          // ── Confirm button ───────────────────────────────────────
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: () {
                widget.onConfirm(_bidAmount, isProxy: _isProxy);
                Navigator.of(context).pop();
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.gold,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusMd,
                ),
              ),
              child: Text(
                _isProxy
                    ? 'تأكيد المزايدة التلقائية'
                    : 'تأكيد المزايدة',
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

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
