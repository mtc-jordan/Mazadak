import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/providers/escrow_provider.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// State-based action buttons for escrow screen.
///
/// SDD §7.2:
/// - SHIPPING_REQUESTED (seller): 'Generate Aramex Label', 'Enter tracking number'
/// - INSPECTION_PERIOD (buyer): 'Confirm receipt', 'Report a problem'
/// - IN_TRANSIT: 'Track shipment'
class EscrowActions extends StatelessWidget {
  const EscrowActions({
    super.key,
    required this.escrow,
    required this.isSeller,
    required this.onGenerateLabel,
    required this.onEnterTracking,
    required this.onConfirmDelivery,
    required this.onReportProblem,
    this.onPayNow,
  });

  final EscrowState escrow;
  final bool isSeller;
  final VoidCallback onGenerateLabel;
  final VoidCallback onEnterTracking;
  final VoidCallback onConfirmDelivery;
  final VoidCallback onReportProblem;
  final VoidCallback? onPayNow;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: AppSpacing.horizontalMd,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: _buildActions(context),
      ),
    );
  }

  List<Widget> _buildActions(BuildContext context) {
    switch (escrow.status) {
      case EscrowStatus.paymentPending when !isSeller:
        return [
          _ActionButton(
            label: 'ادفع الآن',
            icon: Icons.payment_rounded,
            color: AppColors.gold,
            onPressed: onPayNow ?? () {},
            isLoading: escrow.isLoading,
          ),
        ];

      case EscrowStatus.shippingRequested when isSeller:
        return [
          _ActionButton(
            label: 'إنشاء بوليصة أرامكس',
            icon: Icons.local_shipping_rounded,
            color: AppColors.navy,
            onPressed: onGenerateLabel,
            isLoading: escrow.isLoading,
          ),
          const SizedBox(height: AppSpacing.sm),
          _ActionButton(
            label: 'إدخال رقم التتبع',
            icon: Icons.qr_code_rounded,
            color: AppColors.gold,
            onPressed: onEnterTracking,
            outlined: true,
          ),
        ];

      case EscrowStatus.inTransit:
        return [
          if (escrow.trackingUrl != null)
            _ActionButton(
              label: 'تتبع الشحنة',
              icon: Icons.location_on_rounded,
              color: AppColors.navy,
              onPressed: () => _openTrackingUrl(context),
            ),
        ];

      case EscrowStatus.inspectionPeriod when !isSeller:
        return [
          _ActionButton(
            label: 'تأكيد الاستلام',
            icon: Icons.check_circle_rounded,
            color: AppColors.emerald,
            onPressed: onConfirmDelivery,
            isLoading: escrow.isLoading,
          ),
          const SizedBox(height: AppSpacing.sm),
          _ActionButton(
            label: 'الإبلاغ عن مشكلة',
            icon: Icons.report_problem_rounded,
            color: AppColors.ember,
            onPressed: onReportProblem,
            outlined: true,
          ),
        ];

      case EscrowStatus.released:
        return [
          Container(
            padding: AppSpacing.allMd,
            decoration: BoxDecoration(
              color: AppColors.emerald.withOpacity(0.1),
              borderRadius: AppSpacing.radiusMd,
            ),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.check_circle_rounded,
                    color: AppColors.emerald, size: 20),
                SizedBox(width: AppSpacing.xs),
                Text(
                  'تمت المعاملة بنجاح',
                  style: TextStyle(
                    color: AppColors.emerald,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ];

      case EscrowStatus.disputed:
        return [
          Container(
            padding: AppSpacing.allMd,
            decoration: BoxDecoration(
              color: AppColors.ember.withOpacity(0.1),
              borderRadius: AppSpacing.radiusMd,
            ),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.gavel_rounded, color: AppColors.ember, size: 20),
                SizedBox(width: AppSpacing.xs),
                Text(
                  'قيد النزاع — بانتظار المراجعة',
                  style: TextStyle(
                    color: AppColors.ember,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ];

      default:
        return [];
    }
  }

  Future<void> _openTrackingUrl(BuildContext context) async {
    final url = escrow.trackingUrl;
    if (url == null) return;
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.label,
    required this.icon,
    required this.color,
    required this.onPressed,
    this.outlined = false,
    this.isLoading = false,
  });

  final String label;
  final IconData icon;
  final Color color;
  final VoidCallback onPressed;
  final bool outlined;
  final bool isLoading;

  @override
  Widget build(BuildContext context) {
    if (outlined) {
      return SizedBox(
        width: double.infinity,
        height: 48,
        child: OutlinedButton.icon(
          onPressed: isLoading ? null : onPressed,
          icon: Icon(icon, size: 20),
          label: Text(label),
          style: OutlinedButton.styleFrom(
            foregroundColor: color,
            side: BorderSide(color: color),
            shape: RoundedRectangleBorder(
              borderRadius: AppSpacing.radiusMd,
            ),
          ),
        ),
      );
    }

    return SizedBox(
      width: double.infinity,
      height: 48,
      child: ElevatedButton.icon(
        onPressed: isLoading ? null : onPressed,
        icon: isLoading
            ? const SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : Icon(icon, size: 20),
        label: Text(label),
        style: ElevatedButton.styleFrom(
          backgroundColor: color,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: AppSpacing.radiusMd,
          ),
        ),
      ),
    );
  }
}
