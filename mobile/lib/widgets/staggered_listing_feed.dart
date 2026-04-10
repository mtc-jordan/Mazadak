import 'package:flutter/material.dart';

import '../core/providers/listings_provider.dart';
import '../core/theme/spacing.dart';
import 'listing_card.dart';
import 'listing_card_skeleton.dart';

/// Stagger delay between each card entrance.
const _staggerDelay = Duration(milliseconds: 40);
const _cardEntranceDuration = Duration(milliseconds: 300);

/// Home feed with staggered FadeTransition + SlideTransition entrance.
///
/// Each card fades in + slides up from Offset(0, 0.05) with a 40ms
/// stagger delay per card. Uses AnimationController per visible card.
///
/// Shows [ListingGridSkeleton] during loading, then animates in real cards.
class StaggeredListingFeed extends StatefulWidget {
  const StaggeredListingFeed({
    super.key,
    required this.listings,
    required this.isLoading,
    this.onCardTap,
    this.onCardLongPress,
    this.onWatchlistToggle,
    this.onLoadMore,
    this.hasMore = true,
    this.crossAxisCount = 2,
  });

  final List<ListingSummary> listings;
  final bool isLoading;
  final void Function(ListingSummary listing)? onCardTap;
  final void Function(ListingSummary listing)? onCardLongPress;
  final void Function(ListingSummary listing, bool isWatched)? onWatchlistToggle;
  final VoidCallback? onLoadMore;
  final bool hasMore;
  final int crossAxisCount;

  @override
  State<StaggeredListingFeed> createState() => _StaggeredListingFeedState();
}

class _StaggeredListingFeedState extends State<StaggeredListingFeed>
    with TickerProviderStateMixin {
  final List<AnimationController> _controllers = [];
  final List<Animation<double>> _fadeAnimations = [];
  final List<Animation<Offset>> _slideAnimations = [];
  final _scrollController = ScrollController();

  int _animatedCount = 0;

  @override
  void initState() {
    super.initState();
    _scrollController.addListener(_onScroll);
  }

  @override
  void didUpdateWidget(StaggeredListingFeed old) {
    super.didUpdateWidget(old);

    // New items added — create and trigger entrance animations for them
    if (widget.listings.length > _animatedCount) {
      _animateNewItems(from: _animatedCount, to: widget.listings.length);
    }
  }

  void _animateNewItems({required int from, required int to}) {
    for (var i = from; i < to; i++) {
      final controller = AnimationController(
        vsync: this,
        duration: _cardEntranceDuration,
      );
      final fade = CurvedAnimation(
        parent: controller,
        curve: Curves.easeOut,
      );
      final slide = Tween<Offset>(
        begin: const Offset(0, 0.05),
        end: Offset.zero,
      ).animate(CurvedAnimation(
        parent: controller,
        curve: Curves.easeOutCubic,
      ));

      _controllers.add(controller);
      _fadeAnimations.add(fade);
      _slideAnimations.add(slide);
    }

    // Stagger the animations
    _staggerFrom(from, to);
    _animatedCount = to;
  }

  Future<void> _staggerFrom(int from, int to) async {
    for (var i = from; i < to; i++) {
      if (!mounted) return;
      _controllers[i].forward();
      if (i < to - 1) {
        await Future.delayed(_staggerDelay);
      }
    }
  }

  void _onScroll() {
    if (!widget.hasMore || widget.isLoading) return;
    final maxScroll = _scrollController.position.maxScrollExtent;
    final currentScroll = _scrollController.offset;
    if (currentScroll >= maxScroll - 200) {
      widget.onLoadMore?.call();
    }
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    // Loading state — show skeleton grid
    if (widget.isLoading && widget.listings.isEmpty) {
      return ListingGridSkeleton(crossAxisCount: widget.crossAxisCount);
    }

    return GridView.builder(
      controller: _scrollController,
      padding: AppSpacing.allMd,
      gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: widget.crossAxisCount,
        mainAxisSpacing: AppSpacing.sm,
        crossAxisSpacing: AppSpacing.sm,
        childAspectRatio: 0.72,
      ),
      itemCount: widget.listings.length + (widget.isLoading ? 2 : 0),
      itemBuilder: (context, index) {
        // Pagination loading indicators at the end
        if (index >= widget.listings.length) {
          return const ListingCardSkeleton();
        }

        final listing = widget.listings[index];

        // If animation exists for this index, use it
        if (index < _controllers.length) {
          return FadeTransition(
            opacity: _fadeAnimations[index],
            child: SlideTransition(
              position: _slideAnimations[index],
              child: _buildCard(listing),
            ),
          );
        }

        // Fallback (shouldn't normally happen)
        return _buildCard(listing);
      },
    );
  }

  Widget _buildCard(ListingSummary listing) {
    return ListingCard(
      listing: listing,
      onTap: widget.onCardTap != null ? () => widget.onCardTap!(listing) : null,
      onLongPress: widget.onCardLongPress != null
          ? () => widget.onCardLongPress!(listing)
          : null,
      onWatchlistToggle: widget.onWatchlistToggle != null
          ? (watched) => widget.onWatchlistToggle!(listing, watched)
          : null,
    );
  }
}
