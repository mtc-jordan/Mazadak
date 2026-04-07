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
    required this.currency,
    required this.condition,
    required this.status,
    this.bidCount = 0,
    this.endsAt,
  });

  final String id;
  final String titleAr;
  final String? titleEn;
  final String imageUrl;
  final double startingPrice;
  final String currency;
  final String condition;
  final String status;
  final int bidCount;
  final String? endsAt;

  factory ListingSummary.fromJson(Map<String, dynamic> json) => ListingSummary(
        id: json['id'] as String,
        titleAr: json['title_ar'] as String,
        titleEn: json['title_en'] as String?,
        imageUrl: json['image_url'] as String? ?? '',
        startingPrice: (json['starting_price'] as num).toDouble(),
        currency: json['listing_currency'] as String? ?? 'JOD',
        condition: json['condition'] as String,
        status: json['status'] as String,
        bidCount: json['bid_count'] as int? ?? 0,
        endsAt: json['ends_at'] as String?,
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

  Future<void> loadListings({bool refresh = false}) async {
    if (state.isLoading) return;

    final page = refresh ? 1 : state.page;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/listings', queryParameters: {
        'page': page,
        'per_page': 20,
        'status': 'active',
      });

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
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> refresh() => loadListings(refresh: true);
}
