import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';

/// Full listing detail — SDD §5.3 GET /listings/{id}
/// Response: {listing, auction, seller_summary}
class ListingDetail {
  const ListingDetail({
    required this.id,
    required this.titleAr,
    this.titleEn,
    required this.descriptionAr,
    this.descriptionEn,
    required this.imageUrls,
    required this.category,
    required this.condition,
    required this.startingPrice,
    this.currentPrice,
    this.buyNowPrice,
    required this.currency,
    required this.status,
    this.bidCount = 0,
    this.watcherCount = 0,
    this.endsAt,
    this.auctionId,
    this.isLive = false,
    this.isCertified = false,
    this.isCharity = false,
    this.isWatched = false,
    this.isSnapToList = false,
    required this.seller,
    required this.createdAt,
    this.locationCity,
    this.locationCountry,
    this.minIncrement = 2.5,
    this.extensionCount = 0,
    this.viewCount = 0,
  });

  final String id;
  final String titleAr;
  final String? titleEn;
  final String descriptionAr;
  final String? descriptionEn;
  final List<String> imageUrls;
  final String category;
  final String condition;
  final double startingPrice;
  final double? currentPrice;
  final double? buyNowPrice;
  final String currency;
  final String status;
  final int bidCount;
  final int watcherCount;
  final String? endsAt;
  final String? auctionId;
  final bool isLive;
  final bool isCertified;
  final bool isCharity;
  final bool isWatched;
  final bool isSnapToList;
  final SellerSummary seller;
  final String createdAt;
  final String? locationCity;
  final String? locationCountry;
  final double minIncrement;
  final int extensionCount;
  final int viewCount;

  double get displayPrice => currentPrice ?? startingPrice;

  ListingDetail copyWith({
    String? id,
    String? titleAr,
    String? titleEn,
    String? descriptionAr,
    String? descriptionEn,
    List<String>? imageUrls,
    String? category,
    String? condition,
    double? startingPrice,
    double? currentPrice,
    double? buyNowPrice,
    String? currency,
    String? status,
    int? bidCount,
    int? watcherCount,
    String? endsAt,
    String? auctionId,
    bool? isLive,
    bool? isCertified,
    bool? isCharity,
    bool? isWatched,
    bool? isSnapToList,
    SellerSummary? seller,
    String? createdAt,
    String? locationCity,
    String? locationCountry,
    double? minIncrement,
    int? extensionCount,
    int? viewCount,
  }) =>
      ListingDetail(
        id: id ?? this.id,
        titleAr: titleAr ?? this.titleAr,
        titleEn: titleEn ?? this.titleEn,
        descriptionAr: descriptionAr ?? this.descriptionAr,
        descriptionEn: descriptionEn ?? this.descriptionEn,
        imageUrls: imageUrls ?? this.imageUrls,
        category: category ?? this.category,
        condition: condition ?? this.condition,
        startingPrice: startingPrice ?? this.startingPrice,
        currentPrice: currentPrice ?? this.currentPrice,
        buyNowPrice: buyNowPrice ?? this.buyNowPrice,
        currency: currency ?? this.currency,
        status: status ?? this.status,
        bidCount: bidCount ?? this.bidCount,
        watcherCount: watcherCount ?? this.watcherCount,
        endsAt: endsAt ?? this.endsAt,
        auctionId: auctionId ?? this.auctionId,
        isLive: isLive ?? this.isLive,
        isCertified: isCertified ?? this.isCertified,
        isCharity: isCharity ?? this.isCharity,
        isWatched: isWatched ?? this.isWatched,
        isSnapToList: isSnapToList ?? this.isSnapToList,
        seller: seller ?? this.seller,
        createdAt: createdAt ?? this.createdAt,
        locationCity: locationCity ?? this.locationCity,
        locationCountry: locationCountry ?? this.locationCountry,
        minIncrement: minIncrement ?? this.minIncrement,
        extensionCount: extensionCount ?? this.extensionCount,
        viewCount: viewCount ?? this.viewCount,
      );

  factory ListingDetail.fromJson(Map<String, dynamic> json) {
    final listing = json['listing'] as Map<String, dynamic>? ?? json;
    final auction = json['auction'] as Map<String, dynamic>?;
    final sellerJson = json['seller_summary'] as Map<String, dynamic>? ??
        listing['seller_summary'] as Map<String, dynamic>? ??
        {};

    return ListingDetail(
      id: listing['id'] as String,
      titleAr: listing['title_ar'] as String,
      titleEn: listing['title_en'] as String?,
      descriptionAr: listing['description_ar'] as String? ?? '',
      descriptionEn: listing['description_en'] as String?,
      imageUrls: (listing['images'] as List?)
              ?.map((e) => e is String ? e : (e as Map)['url'] as String)
              .toList() ??
          [listing['image_url'] as String? ?? ''],
      category: listing['category'] as String? ?? '',
      condition: listing['condition'] as String? ?? '',
      startingPrice: (listing['starting_price'] as num).toDouble(),
      currentPrice: (listing['current_price'] as num?)?.toDouble() ??
          (auction?['current_price'] as num?)?.toDouble(),
      buyNowPrice: (listing['buy_now_price'] as num?)?.toDouble(),
      currency: listing['listing_currency'] as String? ?? 'JOD',
      status: listing['status'] as String,
      bidCount: auction?['bid_count'] as int? ??
          listing['bid_count'] as int? ??
          0,
      watcherCount: listing['watcher_count'] as int? ?? 0,
      endsAt: auction?['ends_at'] as String? ??
          listing['ends_at'] as String?,
      auctionId: auction?['id'] as String?,
      isLive: auction?['status'] == 'live' ||
          (listing['is_live'] as bool?) == true,
      isCertified: listing['is_authenticated'] as bool? ?? false,
      isCharity: listing['is_charity'] as bool? ?? false,
      isWatched: listing['is_watched'] as bool? ?? false,
      isSnapToList: listing['is_snap_to_list'] as bool? ?? false,
      seller: SellerSummary.fromJson(sellerJson),
      createdAt: listing['created_at'] as String? ?? '',
      locationCity: listing['location_city'] as String?,
      locationCountry: listing['location_country'] as String?,
      minIncrement: (listing['min_increment'] as num?)?.toDouble() ??
          (auction?['min_increment'] as num?)?.toDouble() ??
          2.5,
      extensionCount: auction?['extension_count'] as int? ?? 0,
      viewCount: listing['view_count'] as int? ?? 0,
    );
  }
}

/// Seller summary returned with listing detail.
class SellerSummary {
  const SellerSummary({
    required this.id,
    required this.nameAr,
    this.avatarUrl,
    this.atsScore = 400,
    this.atsTier = 'trusted',
    this.listingsCount = 0,
    this.completionRate = 0,
    this.memberSince,
  });

  final String id;
  final String nameAr;
  final String? avatarUrl;
  final int atsScore;
  final String atsTier;
  final int listingsCount;
  final double completionRate;
  final String? memberSince;

  factory SellerSummary.fromJson(Map<String, dynamic> json) => SellerSummary(
        id: json['id'] as String? ?? '',
        nameAr: json['full_name_ar'] as String? ?? 'بائع',
        avatarUrl: json['avatar_url'] as String?,
        atsScore: json['ats_score'] as int? ?? 400,
        atsTier: json['ats_tier'] as String? ?? 'trusted',
        listingsCount: json['listings_count'] as int? ?? 0,
        completionRate:
            (json['completion_rate'] as num?)?.toDouble() ?? 0,
        memberSince: json['member_since'] as String?,
      );
}

class ListingDetailState {
  const ListingDetailState({
    this.listing,
    this.isLoading = false,
    this.error,
  });

  final ListingDetail? listing;
  final bool isLoading;
  final String? error;
}

/// Provider for a single listing detail page.
final listingDetailProvider = StateNotifierProvider.family<
    ListingDetailNotifier, ListingDetailState, String>((ref, id) {
  return ListingDetailNotifier(ref, id);
});

class ListingDetailNotifier extends StateNotifier<ListingDetailState> {
  ListingDetailNotifier(this._ref, this._id)
      : super(const ListingDetailState()) {
    load();
  }

  final Ref _ref;
  final String _id;

  Future<void> load() async {
    state = const ListingDetailState(isLoading: true);
    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/listings/$_id');
      final detail = ListingDetail.fromJson(
          resp.data as Map<String, dynamic>);
      state = ListingDetailState(listing: detail);
    } catch (_) {
      // Dev fallback: mock listing when backend is unavailable
      state = ListingDetailState(listing: _mockListing(_id));
    }
  }

  static ListingDetail _mockListing(String id) => ListingDetail(
        id: id,
        titleAr: 'ساعة رولكس سبمارينر ٢٠٢٤',
        titleEn: 'Rolex Submariner 2024',
        descriptionAr:
            'ساعة رولكس سبمارينر أصلية موديل ٢٠٢٤، بحالة ممتازة مع جميع الأوراق والضمان الأصلي. '
            'حركة أوتوماتيكية، مقاومة للماء حتى ٣٠٠ متر.',
        imageUrls: [
          'https://picsum.photos/seed/rolex1/800/600',
          'https://picsum.photos/seed/rolex2/800/600',
          'https://picsum.photos/seed/rolex3/800/600',
        ],
        category: 'Watches',
        condition: 'New',
        startingPrice: 8500,
        currentPrice: 12750,
        buyNowPrice: 15000,
        currency: 'JOD',
        status: 'active',
        bidCount: 23,
        watcherCount: 47,
        endsAt: DateTime.now()
            .toUtc()
            .add(const Duration(hours: 2, minutes: 15))
            .toIso8601String(),
        auctionId: 'auction-$id',
        isLive: true,
        isCertified: true,
        seller: const SellerSummary(
          id: 'seller-1',
          nameAr: 'محمد الأحمد',
          atsScore: 820,
          atsTier: 'pro',
          listingsCount: 34,
          completionRate: 0.92,
        ),
        createdAt: DateTime.now()
            .toUtc()
            .subtract(const Duration(days: 3))
            .toIso8601String(),
        locationCity: 'عمّان',
        locationCountry: 'الأردن',
        minIncrement: 5.0,
        extensionCount: 2,
        viewCount: 156,
      );

  Future<void> toggleWatchlist() async {
    final listing = state.listing;
    if (listing == null) return;

    try {
      final api = _ref.read(apiClientProvider);
      if (listing.isWatched) {
        await api.delete('/listings/${listing.id}/watch');
      } else {
        await api.post('/listings/${listing.id}/watch');
      }
      _rebuildWithWatchToggle(listing);
    } catch (_) {
      // Dev fallback: toggle locally even if API unavailable
      _rebuildWithWatchToggle(listing);
    }
  }

  void _rebuildWithWatchToggle(ListingDetail listing) {
    state = ListingDetailState(
      listing: listing.copyWith(isWatched: !listing.isWatched),
    );
  }
}
