import 'package:flutter/material.dart';

import '../../../core/providers/listing_detail_provider.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Seller ATS (Auction Trust Score) badge shown on listing detail.
///
/// Displays seller name, avatar, ATS score with tier color, and
/// listings count. ATS tiers:
/// - starter (<300): mist
/// - trusted (300-599): navy
/// - pro (600-799): gold
/// - elite (800-1000): emerald
class SellerAtsBadge extends StatelessWidget {
  const SellerAtsBadge({super.key, required this.seller});

  final SellerSummary seller;

  Color get _tierColor => switch (seller.atsTier) {
        'elite' => AppColors.emerald,
        'pro' => AppColors.gold,
        'trusted' => AppColors.navy,
        _ => AppColors.mist,
      };

  String get _tierLabel => switch (seller.atsTier) {
        'elite' => 'نخبة',
        'pro' => 'محترف',
        'trusted' => 'موثوق',
        _ => 'مبتدئ',
      };

  IconData get _tierIcon => switch (seller.atsTier) {
        'elite' => Icons.diamond_rounded,
        'pro' => Icons.workspace_premium_rounded,
        'trusted' => Icons.verified_user_rounded,
        _ => Icons.person_rounded,
      };

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        // Avatar
        Container(
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            color: _tierColor.withOpacity(0.12),
            shape: BoxShape.circle,
          ),
          child: seller.avatarUrl != null
              ? ClipOval(
                  child: Image.network(seller.avatarUrl!, fit: BoxFit.cover),
                )
              : Icon(Icons.person, color: _tierColor, size: 24),
        ),
        const SizedBox(width: AppSpacing.sm),

        // Name + tier
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                seller.nameAr,
                style: const TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(height: 2),
              Row(
                children: [
                  Icon(_tierIcon, color: _tierColor, size: 14),
                  const SizedBox(width: 4),
                  Text(
                    _tierLabel,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: _tierColor,
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Text(
                    '• ${seller.listingsCount} قائمة',
                    style: const TextStyle(
                      fontSize: 12,
                      color: AppColors.mist,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),

        // ATS score badge
        Container(
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: _tierColor.withOpacity(0.1),
            borderRadius: AppSpacing.radiusMd,
            border: Border.all(color: _tierColor.withOpacity(0.3)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${seller.atsScore}',
                style: TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w800,
                  color: _tierColor,
                  fontFamily: 'Sora',
                ),
              ),
              const Text(
                'ATS',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                  color: AppColors.mist,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
