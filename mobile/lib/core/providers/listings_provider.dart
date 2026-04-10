import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';

/// Single listing model (minimal for provider layer).
class ListingSummary {
  const ListingSummary({
    required this.id,
    required this.titleAr,
    this.titleEn,
    required this.imageUrl,
    required this.startingPrice,
    this.currentPrice,
    required this.currency,
    required this.condition,
    required this.status,
    this.bidCount = 0,
    this.endsAt,
    this.isLive = false,
    this.isCertified = false,
    this.buyNowPrice,
    this.isCharity = false,
    this.isWatched = false,
    this.winnerName,
  });

  final String id;
  final String titleAr;
  final String? titleEn;
  final String imageUrl;
  final double startingPrice;
  final double? currentPrice;
  final String currency;
  final String condition;
  final String status;
  final int bidCount;
  final String? endsAt;
  final bool isLive;
  final bool isCertified;
  final double? buyNowPrice;
  final bool isCharity;
  final bool isWatched;
  final String? winnerName;

  /// Effective display price: current bid or starting price.
  double get displayPrice => currentPrice ?? startingPrice;

  factory ListingSummary.fromJson(Map<String, dynamic> json) => ListingSummary(
        id: json['id'] as String,
        titleAr: json['title_ar'] as String,
        titleEn: json['title_en'] as String?,
        imageUrl: json['image_url'] as String? ?? '',
        startingPrice: (json['starting_price'] as num).toDouble(),
        currentPrice: (json['current_price'] as num?)?.toDouble(),
        currency: json['listing_currency'] as String? ?? 'JOD',
        condition: json['condition'] as String,
        status: json['status'] as String,
        bidCount: json['bid_count'] as int? ?? 0,
        endsAt: json['ends_at'] as String?,
        isLive: json['is_live'] as bool? ?? false,
        isCertified: json['is_authenticated'] as bool? ?? false,
        buyNowPrice: (json['buy_now_price'] as num?)?.toDouble(),
        isCharity: json['is_charity'] as bool? ?? false,
        isWatched: json['is_watched'] as bool? ?? false,
        winnerName: json['winner_name'] as String?,
      );
}

class ListingsState {
  const ListingsState({
    this.listings = const [],
    this.isLoading = false,
    this.error,
    this.page = 1,
    this.hasMore = true,
  });

  final List<ListingSummary> listings;
  final bool isLoading;
  final String? error;
  final int page;
  final bool hasMore;

  ListingsState copyWith({
    List<ListingSummary>? listings,
    bool? isLoading,
    String? error,
    int? page,
    bool? hasMore,
  }) => ListingsState(
        listings: listings ?? this.listings,
        isLoading: isLoading ?? this.isLoading,
        error: error,
        page: page ?? this.page,
        hasMore: hasMore ?? this.hasMore,
      );
}

/// Listings provider — SDD §7.1 listingsProvider.
///
/// Fetches paginated active listings with pull-to-refresh and infinite scroll.
final listingsProvider =
    StateNotifierProvider<ListingsNotifier, ListingsState>((ref) {
  return ListingsNotifier(ref);
});

class ListingsNotifier extends StateNotifier<ListingsState> {
  ListingsNotifier(this._ref) : super(const ListingsState()) {
    loadListings();
  }

  final Ref _ref;
  String? _categoryId;

  Future<void> loadListings({bool refresh = false}) async {
    if (state.isLoading) return;

    final page = refresh ? 1 : state.page;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);
      final params = <String, dynamic>{
        'page': page,
        'per_page': 20,
        'status': 'active',
        'sort': 'ends_asc',
      };
      if (_categoryId != null) {
        params['category_id'] = _categoryId;
      }
      final resp = await api.get('/listings', queryParameters: params);

      final data = resp.data as Map<String, dynamic>;
      final items = (data['items'] as List)
          .map((e) => ListingSummary.fromJson(e as Map<String, dynamic>))
          .toList();

      state = state.copyWith(
        listings: refresh ? items : [...state.listings, ...items],
        isLoading: false,
        page: page + 1,
        hasMore: items.length >= 20,
      );
    } catch (e) {
      // Fallback to mock data when backend is unavailable (dev mode)
      if (state.listings.isEmpty) {
        state = state.copyWith(
          listings: _mockListings,
          isLoading: false,
          hasMore: false,
        );
      } else {
        state = state.copyWith(isLoading: false, error: e.toString());
      }
    }
  }

  static final _mockListings = [
    ListingSummary(
      id: 'mock-1',
      titleAr: 'ساعة رولكس سبمارينر ٢٠٢٤',
      titleEn: 'Rolex Submariner 2024',
      imageUrl: 'https://picsum.photos/seed/rolex/400/300',
      startingPrice: 8500,
      currentPrice: 12750,
      currency: 'JOD',
      condition: 'New',
      status: 'active',
      bidCount: 23,
      endsAt: DateTime.now().toUtc().add(const Duration(hours: 2, minutes: 15)).toIso8601String(),
      isLive: true,
      isCertified: true,
    ),
    ListingSummary(
      id: 'mock-2',
      titleAr: 'آيفون ١٥ برو ماكس ٢٥٦ جيجا',
      titleEn: 'iPhone 15 Pro Max 256GB',
      imageUrl: 'https://picsum.photos/seed/iphone/400/300',
      startingPrice: 350,
      currentPrice: 520,
      currency: 'JOD',
      condition: 'Like New',
      status: 'active',
      bidCount: 14,
      endsAt: DateTime.now().toUtc().add(const Duration(minutes: 45)).toIso8601String(),
    ),
    ListingSummary(
      id: 'mock-3',
      titleAr: 'مرسيدس بنز C200 موديل ٢٠٢٢',
      titleEn: 'Mercedes-Benz C200 2022',
      imageUrl: 'https://picsum.photos/seed/mercedes/400/300',
      startingPrice: 25000,
      currentPrice: 28500,
      currency: 'JOD',
      condition: 'Excellent',
      status: 'active',
      bidCount: 8,
      endsAt: DateTime.now().toUtc().add(const Duration(days: 1, hours: 6)).toIso8601String(),
      isCertified: true,
    ),
    ListingSummary(
      id: 'mock-4',
      titleAr: 'لوحة فنية أصلية — خط عربي',
      titleEn: 'Original Arabic Calligraphy Art',
      imageUrl: 'https://picsum.photos/seed/art/400/300',
      startingPrice: 150,
      currentPrice: 280,
      currency: 'JOD',
      condition: 'New',
      status: 'active',
      bidCount: 6,
      endsAt: DateTime.now().toUtc().add(const Duration(hours: 8)).toIso8601String(),
      isCharity: true,
    ),
    ListingSummary(
      id: 'mock-5',
      titleAr: 'سوار ذهب عيار ٢١',
      titleEn: 'Gold Bracelet 21K',
      imageUrl: 'https://picsum.photos/seed/gold/400/300',
      startingPrice: 400,
      currentPrice: 650,
      currency: 'JOD',
      condition: 'New',
      status: 'active',
      bidCount: 19,
      endsAt: DateTime.now().toUtc().add(const Duration(hours: 4, minutes: 30)).toIso8601String(),
      isCertified: true,
    ),
    ListingSummary(
      id: 'mock-6',
      titleAr: 'بلايستيشن ٥ مع ألعاب',
      titleEn: 'PlayStation 5 Bundle',
      imageUrl: 'https://picsum.photos/seed/ps5/400/300',
      startingPrice: 180,
      currentPrice: 245,
      currency: 'JOD',
      condition: 'Used',
      status: 'active',
      bidCount: 11,
      endsAt: DateTime.now().toUtc().add(const Duration(minutes: 3)).toIso8601String(),
    ),
    ListingSummary(
      id: 'mock-7',
      titleAr: 'عقد ألماس طبيعي',
      titleEn: 'Natural Diamond Necklace',
      imageUrl: 'https://picsum.photos/seed/diamond/400/300',
      startingPrice: 2000,
      currentPrice: 3200,
      currency: 'JOD',
      condition: 'New',
      status: 'active',
      bidCount: 31,
      endsAt: DateTime.now().toUtc().add(const Duration(hours: 1)).toIso8601String(),
      isLive: true,
      isCertified: true,
    ),
    ListingSummary(
      id: 'mock-8',
      titleAr: 'طاولة أنتيك عثمانية',
      titleEn: 'Ottoman Antique Table',
      imageUrl: 'https://picsum.photos/seed/antique/400/300',
      startingPrice: 500,
      currency: 'JOD',
      condition: 'Antique',
      status: 'active',
      bidCount: 3,
      endsAt: DateTime.now().toUtc().add(const Duration(days: 3)).toIso8601String(),
    ),
  ];

  Future<void> refresh() => loadListings(refresh: true);

  void filterByCategory(String? categoryId) {
    _categoryId = categoryId;
    loadListings(refresh: true);
  }
}
