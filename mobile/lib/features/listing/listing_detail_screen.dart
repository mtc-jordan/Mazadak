import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/listing_detail_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import 'widgets/seller_ats_badge.dart';

/// Listing detail screen — tap from home feed card.
///
/// Hero image flies from ListingCard via HeroTags.listingImage(id).
/// Shows: image gallery, title, price, condition, seller ATS score,
/// description, bid button CTA.
class ListingDetailScreen extends ConsumerWidget {
  const ListingDetailScreen({super.key, required this.listingId});

  final String listingId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(listingDetailProvider(listingId));

    if (state.isLoading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(color: AppColors.gold)),
      );
    }

    if (state.error != null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(
          child: Text(state.error!, style: const TextStyle(color: AppColors.ember)),
        ),
      );
    }

    final listing = state.listing!;

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          // ── Hero image header ───────────────────────────────────
          _ImageHeader(listing: listing, listingId: listingId),

          // ── Content ─────────────────────────────────────────────
          SliverToBoxAdapter(
            child: Padding(
              padding: AppSpacing.allMd,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Badges row
                  _BadgesRow(listing: listing),
                  const SizedBox(height: AppSpacing.sm),

                  // Title
                  Text(
                    listing.titleAr,
                    style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ink,
                      height: 1.3,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),

                  // Price + bid count
                  Row(
                    children: [
                      Text(
                        ArabicNumerals.formatCurrency(
                          listing.displayPrice,
                          listing.currency,
                        ),
                        style: const TextStyle(
                          fontSize: 24,
                          fontWeight: FontWeight.w700,
                          color: AppColors.navy,
                          fontFamily: 'Sora',
                        ),
                      ),
                      const Spacer(),
                      Text(
                        '${ArabicNumerals.formatNumber(listing.bidCount)} مزايدة',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.mist,
                        ),
                      ),
                    ],
                  ),

                  // Buy now price
                  if (listing.buyNowPrice != null) ...[
                    const SizedBox(height: AppSpacing.xxs),
                    Text(
                      'شراء فوري: ${ArabicNumerals.formatCurrency(listing.buyNowPrice!, listing.currency)}',
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppColors.gold,
                      ),
                    ),
                  ],

                  const SizedBox(height: AppSpacing.lg),
                  const Divider(color: AppColors.sand),
                  const SizedBox(height: AppSpacing.md),

                  // ── Seller section with ATS score ──────────────
                  SellerAtsBadge(seller: listing.seller),

                  const SizedBox(height: AppSpacing.lg),
                  const Divider(color: AppColors.sand),
                  const SizedBox(height: AppSpacing.md),

                  // ── Details section ────────────────────────────
                  _DetailRow(label: 'الفئة', value: listing.category),
                  _DetailRow(
                    label: 'الحالة',
                    value: listing.condition,
                    valueColor: _conditionColor(listing.condition),
                  ),
                  if (listing.watcherCount > 0)
                    _DetailRow(
                      label: 'المتابعون',
                      value: '${ArabicNumerals.formatNumber(listing.watcherCount)} شخص',
                    ),

                  const SizedBox(height: AppSpacing.lg),

                  // ── Description ─────────────────────────────────
                  const Text(
                    'الوصف',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    listing.descriptionAr,
                    style: const TextStyle(
                      fontSize: 14,
                      color: AppColors.ink,
                      height: 1.6,
                    ),
                  ),

                  // Bottom spacing for the fixed bid button
                  const SizedBox(height: 100),
                ],
              ),
            ),
          ),
        ],
      ),

      // ── Fixed bottom bid button ──────────────────────────────────
      bottomNavigationBar: _BottomBidBar(listing: listing),
    );
  }

  Color _conditionColor(String condition) {
    final lower = condition.toLowerCase();
    if (lower.contains('new') || lower.contains('جديد')) return AppColors.emerald;
    if (lower.contains('like new') || lower.contains('ممتاز')) return const Color(0xFF30A06A);
    if (lower.contains('good') || lower.contains('جيد')) return AppColors.gold;
    return AppColors.mist;
  }
}

// ── Hero image header with watchlist heart ──────────────────────────

class _ImageHeader extends StatelessWidget {
  const _ImageHeader({required this.listing, required this.listingId});

  final ListingDetail listing;
  final String listingId;

  @override
  Widget build(BuildContext context) {
    return SliverAppBar(
      expandedHeight: 280,
      pinned: true,
      backgroundColor: Colors.white,
      foregroundColor: AppColors.navy,
      flexibleSpace: FlexibleSpaceBar(
        background: Hero(
          tag: HeroTags.listingImage(listingId),
          child: CachedNetworkImage(
            imageUrl: listing.imageUrls.isNotEmpty
                ? listing.imageUrls.first
                : '',
            fit: BoxFit.cover,
            placeholder: (_, __) => Container(color: AppColors.sand),
            errorWidget: (_, __, ___) => Container(
              color: AppColors.sand,
              child: const Icon(Icons.image_not_supported_rounded,
                  color: AppColors.mist, size: 48),
            ),
          ),
        ),
      ),
      actions: [
        // Watchlist heart
        Consumer(
          builder: (context, ref, _) {
            final isWatched = ref
                    .watch(listingDetailProvider(listingId))
                    .listing
                    ?.isWatched ??
                false;

            return IconButton(
              onPressed: () {
                HapticFeedback.lightImpact();
                ref
                    .read(listingDetailProvider(listingId).notifier)
                    .toggleWatchlist();
              },
              icon: AnimatedSwitcher(
                duration: const Duration(milliseconds: 300),
                transitionBuilder: (child, anim) => ScaleTransition(
                  scale: anim,
                  child: child,
                ),
                child: Icon(
                  isWatched
                      ? Icons.favorite_rounded
                      : Icons.favorite_border_rounded,
                  key: ValueKey(isWatched),
                  color: isWatched ? AppColors.ember : AppColors.navy,
                ),
              ),
            );
          },
        ),
        // Share
        IconButton(
          onPressed: () {},
          icon: const Icon(Icons.share_rounded),
        ),
      ],
    );
  }
}

// ── Badges row ──────────────────────────────────────────────────────

class _BadgesRow extends StatelessWidget {
  const _BadgesRow({required this.listing});

  final ListingDetail listing;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: AppSpacing.xs,
      runSpacing: AppSpacing.xxs,
      children: [
        if (listing.isLive)
          _Chip(label: 'مباشر', color: AppColors.ember, icon: Icons.circle),
        if (listing.isCertified)
          _Chip(label: 'موثّق', color: AppColors.emerald, icon: Icons.verified_rounded),
        if (listing.buyNowPrice != null)
          _Chip(label: 'شراء فوري', color: AppColors.gold, icon: Icons.bolt_rounded),
        if (listing.isCharity)
          _Chip(label: 'خيري', color: const Color(0xFF0D8A72), icon: Icons.favorite_rounded),
        if (listing.isSnapToList)
          _Chip(label: 'Snap-to-List', color: AppColors.navy, icon: Icons.auto_awesome_rounded),
      ],
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.color, this.icon});

  final String label;
  final Color color;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, color: color, size: 12),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
        ],
      ),
    );
  }
}

// ── Detail row ──────────────────────────────────────────────────────

class _DetailRow extends StatelessWidget {
  const _DetailRow({
    required this.label,
    required this.value,
    this.valueColor,
  });

  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
      child: Row(
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 14, color: AppColors.mist),
          ),
          const Spacer(),
          Text(
            value,
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: valueColor ?? AppColors.ink,
            ),
          ),
        ],
      ),
    );
  }
}

// ── Bottom bid bar ──────────────────────────────────────────────────

class _BottomBidBar extends StatelessWidget {
  const _BottomBidBar({required this.listing});

  final ListingDetail listing;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsetsDirectional.only(
        start: AppSpacing.md,
        end: AppSpacing.md,
        top: AppSpacing.sm,
        bottom: MediaQuery.of(context).viewPadding.bottom + AppSpacing.sm,
      ),
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: AppColors.sand)),
      ),
      child: Row(
        children: [
          // Price column
          Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'السعر الحالي',
                style: TextStyle(fontSize: 12, color: AppColors.mist),
              ),
              Text(
                ArabicNumerals.formatCurrency(
                  listing.displayPrice,
                  listing.currency,
                ),
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                  fontFamily: 'Sora',
                ),
              ),
            ],
          ),
          const SizedBox(width: AppSpacing.md),

          // Bid button
          Expanded(
            child: SizedBox(
              height: 48,
              child: Material(
                color: AppColors.gold,
                borderRadius: AppSpacing.radiusMd,
                child: InkWell(
                  onTap: () {
                    HapticFeedback.lightImpact();
                    if (listing.auctionId != null) {
                      context.push('/auction/${listing.auctionId}');
                    }
                  },
                  borderRadius: AppSpacing.radiusMd,
                  child: const Center(
                    child: Text(
                      'ضع مزايدتك',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: Colors.white,
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
