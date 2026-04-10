import 'package:flutter/material.dart';

import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Modal bottom sheet for entering tracking number and carrier.
class ShippingForm extends StatefulWidget {
  const ShippingForm({
    super.key,
    required this.onSubmit,
  });

  final void Function(String trackingNumber, String carrier) onSubmit;

  /// Show the sheet as a modal bottom sheet.
  static Future<void> show({
    required BuildContext context,
    required void Function(String trackingNumber, String carrier) onSubmit,
  }) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => ShippingForm(onSubmit: onSubmit),
    );
  }

  @override
  State<ShippingForm> createState() => _ShippingFormState();
}

class _ShippingFormState extends State<ShippingForm> {
  final _trackingController = TextEditingController();
  String _selectedCarrier = 'aramex';

  static const _carriers = [
    ('aramex', 'أرامكس'),
    ('dhl', 'DHL'),
    ('fedex', 'FedEx'),
    ('other', 'أخرى'),
  ];

  bool get _isValid => _trackingController.text.trim().isNotEmpty;

  @override
  void dispose() {
    _trackingController.dispose();
    super.dispose();
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
          // Drag handle
          Container(
            width: 40,
            height: 4,
            decoration: BoxDecoration(
              color: AppColors.sand,
              borderRadius: AppSpacing.radiusFull,
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // Title
          const Text(
            'إدخال رقم التتبع',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w700,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // Carrier selector
          Wrap(
            spacing: AppSpacing.xs,
            children: _carriers.map((c) {
              final isSelected = _selectedCarrier == c.$1;
              return ChoiceChip(
                label: Text(c.$2),
                selected: isSelected,
                onSelected: (_) => setState(() => _selectedCarrier = c.$1),
                selectedColor: AppColors.navy,
                labelStyle: TextStyle(
                  color: isSelected ? Colors.white : AppColors.ink,
                  fontSize: 13,
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: AppSpacing.md),

          // Tracking number input
          TextField(
            controller: _trackingController,
            textDirection: TextDirection.ltr,
            decoration: InputDecoration(
              labelText: 'رقم التتبع',
              hintText: 'مثال: 1234567890',
              hintTextDirection: TextDirection.ltr,
              prefixIcon: const Icon(Icons.qr_code_rounded),
              border: OutlineInputBorder(
                borderRadius: AppSpacing.radiusMd,
              ),
            ),
            onChanged: (_) => setState(() {}),
          ),
          const SizedBox(height: AppSpacing.lg),

          // Submit button
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: _isValid
                  ? () {
                      widget.onSubmit(
                        _trackingController.text.trim(),
                        _selectedCarrier,
                      );
                      Navigator.of(context).pop();
                    }
                  : null,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.navy,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusMd,
                ),
              ),
              child: const Text(
                'تأكيد رقم التتبع',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
