import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';
import 'listings_provider.dart';

// ═══════════════════════════════════════════════════════════════════
//  Home Feed State
// ═══════════════════════════════════════════════════════════════════

class HomeFeedState {
  const HomeFeedState({
    this.featured = const [],
    this.liveNow = const [],
    this.endingSoon = const [],
    this.trending = const [],
    this.newListings = const [],
    this.isLoading = false,
    this.error,
  });

  final List<ListingSummary> featured;
  final List<ListingSummary> liveNow;
  final List<ListingSummary> endingSoon;
  final List<ListingSummary> trending;
  final List<ListingSummary> newListings;
  final bool isLoading;
  final String? error;

  HomeFeedState copyWith({
    List<ListingSummary>? featured,
    List<ListingSummary>? liveNow,
    List<ListingSummary>? endingSoon,
    List<ListingSummary>? trending,
    List<ListingSummary>? newListings,
    bool? isLoading,
    String? error,
  }) =>
      HomeFeedState(
        featured: featured ?? this.featured,
        liveNow: liveNow ?? this.liveNow,
        endingSoon: endingSoon ?? this.endingSoon,
        trending: trending ?? this.trending,
        newListings: newListings ?? this.newListings,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

// ═══════════════════════════════════════════════════════════════════
//  Home Feed Provider
// ═══════════════════════════════════════════════════════════════════

final homeFeedProvider =
    StateNotifierProvider<HomeFeedNotifier, HomeFeedState>((ref) {
  return HomeFeedNotifier(ref);
});

class HomeFeedNotifier extends StateNotifier<HomeFeedState> {
  HomeFeedNotifier(this._ref) : super(const HomeFeedState()) {
    loadFeed();
  }

  final Ref _ref;
  int? _categoryId;

  /// Fire 4 parallel API calls composing the full home feed.
  Future<void> loadFeed() async {
    if (state.isLoading) return;
    state = state.copyWith(isLoading: true, error: null);

    try {
      final api = _ref.read(apiClientProvider);

      Map<String, dynamic> _params(String sort, int limit) {
        final p = <String, dynamic>{
          'status': 'active',
          'sort': sort,
          'per_page': limit,
          'page': 1,
        };
        if (_categoryId != null) p['category_id'] = _categoryId;
        return p;
      }

      final results = await Future.wait([
        api.get('/listings', queryParameters: _params('ends_asc', 10)),
        api.get('/listings', queryParameters: _params('bid_count_desc', 8)),
        api.get('/listings', queryParameters: _params('newest', 10)),
        api.get('/listings', queryParameters: _params('price_desc', 3)),
      ]);

      List<ListingSummary> _parse(dynamic resp) {
        final data = resp.data as Map<String, dynamic>;
        return (data['items'] as List)
            .map((e) => ListingSummary.fromJson(e as Map<String, dynamic>))
            .toList();
      }

      final endingSoon = _parse(results[0]);
      final trending = _parse(results[1]);
      final newListings = _parse(results[2]);
      final featured = _parse(results[3]);

      // Live listings = those from endingSoon with isLive flag
      final liveNow = endingSoon.where((l) => l.isLive).toList();

      state = state.copyWith(
        endingSoon: endingSoon.where((l) => !l.isLive).toList(),
        trending: trending,
        newListings: newListings,
        featured: featured,
        liveNow: liveNow,
        isLoading: false,
      );
    } catch (e) {
      // Fallback to mock data when backend unavailable (dev mode)
      if (_hasNoData) {
        _loadMockData();
      } else {
        state = state.copyWith(isLoading: false, error: e.toString());
      }
    }
  }

  bool get _hasNoData =>
      state.endingSoon.isEmpty &&
      state.trending.isEmpty &&
      state.newListings.isEmpty;

  void _loadMockData() {
    final now = DateTime.now().toUtc();
    final mocks = [
      ListingSummary(
        id: 'hf-1',
        titleAr: 'ساعة رولكس سبمارينر ٢٠٢٤',
        titleEn: 'Rolex Submariner 2024',
        imageUrl: 'https://picsum.photos/seed/rolex/400/300',
        startingPrice: 8500,
        currentPrice: 12750,
        currency: 'JOD',
        condition: 'New',
        status: 'active',
        bidCount: 23,
        endsAt: now.add(const Duration(hours: 2, minutes: 15)).toIso8601String(),
        isLive: true,
        isCertified: true,
      ),
      ListingSummary(
        id: 'hf-2',
        titleAr: 'آيفون ١٥ برو ماكس ٢٥٦ جيجا',
        titleEn: 'iPhone 15 Pro Max 256GB',
        imageUrl: 'https://picsum.photos/seed/iphone15/400/300',
        startingPrice: 350,
        currentPrice: 520,
        currency: 'JOD',
        condition: 'Like New',
        status: 'active',
        bidCount: 14,
        endsAt: now.add(const Duration(minutes: 45)).toIso8601String(),
      ),
      ListingSummary(
        id: 'hf-3',
        titleAr: 'مرسيدس بنز C200 موديل ٢٠٢٢',
        titleEn: 'Mercedes-Benz C200 2022',
        imageUrl: 'https://picsum.photos/seed/benz/400/300',
        startingPrice: 25000,
        currentPrice: 28500,
        currency: 'JOD',
        condition: 'Excellent',
        status: 'active',
        bidCount: 8,
        endsAt: now.add(const Duration(days: 1, hours: 6)).toIso8601String(),
        isCertified: true,
      ),
      ListingSummary(
        id: 'hf-4',
        titleAr: 'عقد ألماس طبيعي',
        titleEn: 'Natural Diamond Necklace',
        imageUrl: 'https://picsum.photos/seed/diamond2/400/300',
        startingPrice: 2000,
        currentPrice: 3200,
        currency: 'JOD',
        condition: 'New',
        status: 'active',
        bidCount: 31,
        endsAt: now.add(const Duration(hours: 1)).toIso8601String(),
        isLive: true,
        isCertified: true,
      ),
      ListingSummary(
        id: 'hf-5',
        titleAr: 'سوار ذهب عيار ٢١',
        titleEn: 'Gold Bracelet 21K',
        imageUrl: 'https://picsum.photos/seed/gold21/400/300',
        startingPrice: 400,
        currentPrice: 650,
        currency: 'JOD',
        condition: 'New',
        status: 'active',
        bidCount: 19,
        endsAt: now.add(const Duration(hours: 4, minutes: 30)).toIso8601String(),
        isCertified: true,
      ),
      ListingSummary(
        id: 'hf-6',
        titleAr: 'بلايستيشن ٥ مع ألعاب',
        titleEn: 'PlayStation 5 Bundle',
        imageUrl: 'https://picsum.photos/seed/ps5x/400/300',
        startingPrice: 180,
        currentPrice: 245,
        currency: 'JOD',
        condition: 'Used',
        status: 'active',
        bidCount: 11,
        endsAt: now.add(const Duration(minutes: 3)).toIso8601String(),
      ),
      ListingSummary(
        id: 'hf-7',
        titleAr: 'لوحة فنية أصلية — خط عربي',
        titleEn: 'Original Arabic Calligraphy Art',
        imageUrl: 'https://picsum.photos/seed/calligraphy/400/300',
        startingPrice: 150,
        currentPrice: 280,
        currency: 'JOD',
        condition: 'New',
        status: 'active',
        bidCount: 6,
        endsAt: now.add(const Duration(hours: 8)).toIso8601String(),
        isCharity: true,
      ),
      ListingSummary(
        id: 'hf-8',
        titleAr: 'طاولة أنتيك عثمانية',
        titleEn: 'Ottoman Antique Table',
        imageUrl: 'https://picsum.photos/seed/ottoman/400/300',
        startingPrice: 500,
        currentPrice: 720,
        currency: 'JOD',
        condition: 'Antique',
        status: 'active',
        bidCount: 3,
        endsAt: now.add(const Duration(days: 3)).toIso8601String(),
      ),
    ];

    // Distribute mock data across sections
    final live = mocks.where((l) => l.isLive).toList();
    final ending = mocks
        .where((l) => !l.isLive)
        .toList()
      ..sort((a, b) => (a.endsAt ?? '').compareTo(b.endsAt ?? ''));
    final byBids = List<ListingSummary>.from(mocks)
      ..sort((a, b) => b.bidCount.compareTo(a.bidCount));
    final byPrice = List<ListingSummary>.from(mocks)
      ..sort((a, b) => b.displayPrice.compareTo(a.displayPrice));

    state = state.copyWith(
      liveNow: live,
      endingSoon: ending,
      trending: byBids.take(6).toList(),
      newListings: mocks,
      featured: byPrice.take(3).toList(),
      isLoading: false,
    );
  }

  Future<void> refresh() => loadFeed();

  void filterByCategory(int? categoryId) {
    _categoryId = categoryId;
    state = const HomeFeedState(); // reset
    loadFeed();
  }
}
