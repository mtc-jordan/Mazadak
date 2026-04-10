import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';
import 'listings_provider.dart';

// ═══════════════════════════════════════════════════════════════════
// Search Filters
// ═══════════════════════════════════════════════════════════════════

class SearchFilters {
  const SearchFilters({
    this.query,
    this.categoryId,
    this.condition,
    this.priceMin,
    this.priceMax,
    this.isCertified,
    this.sort = 'ends_asc',
  });

  final String? query;
  final int? categoryId;
  final String? condition;
  final int? priceMin; // cents
  final int? priceMax; // cents
  final bool? isCertified;
  final String sort;

  /// Number of active filters (excluding query and default sort).
  int get activeCount {
    int count = 0;
    if (categoryId != null) count++;
    if (condition != null) count++;
    if (priceMin != null) count++;
    if (priceMax != null) count++;
    if (isCertified == true) count++;
    if (sort != 'ends_asc') count++;
    return count;
  }

  bool get hasActiveFilters => activeCount > 0;

  SearchFilters copyWith({
    String? query,
    int? categoryId,
    String? condition,
    int? priceMin,
    int? priceMax,
    bool? isCertified,
    String? sort,
    bool clearQuery = false,
    bool clearCategory = false,
    bool clearCondition = false,
    bool clearPriceMin = false,
    bool clearPriceMax = false,
    bool clearCertified = false,
  }) {
    return SearchFilters(
      query: clearQuery ? null : (query ?? this.query),
      categoryId: clearCategory ? null : (categoryId ?? this.categoryId),
      condition: clearCondition ? null : (condition ?? this.condition),
      priceMin: clearPriceMin ? null : (priceMin ?? this.priceMin),
      priceMax: clearPriceMax ? null : (priceMax ?? this.priceMax),
      isCertified: clearCertified ? null : (isCertified ?? this.isCertified),
      sort: sort ?? this.sort,
    );
  }

  static const empty = SearchFilters();
}

// ═══════════════════════════════════════════════════════════════════
// Search State
// ═══════════════════════════════════════════════════════════════════

class SearchState {
  const SearchState({
    this.results = const [],
    this.isLoading = false,
    this.error,
    this.filters = const SearchFilters(),
    this.total = 0,
    this.hasMore = false,
    this.offset = 0,
  });

  final List<ListingSummary> results;
  final bool isLoading;
  final String? error;
  final SearchFilters filters;
  final int total;
  final bool hasMore;
  final int offset;

  SearchState copyWith({
    List<ListingSummary>? results,
    bool? isLoading,
    String? error,
    SearchFilters? filters,
    int? total,
    bool? hasMore,
    int? offset,
    bool clearError = false,
  }) {
    return SearchState(
      results: results ?? this.results,
      isLoading: isLoading ?? this.isLoading,
      error: clearError ? null : (error ?? this.error),
      filters: filters ?? this.filters,
      total: total ?? this.total,
      hasMore: hasMore ?? this.hasMore,
      offset: offset ?? this.offset,
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Search Provider
// ═══════════════════════════════════════════════════════════════════

const _pageSize = 20;

final searchProvider =
    StateNotifierProvider.autoDispose<SearchNotifier, SearchState>(
  (ref) => SearchNotifier(ref),
);

class SearchNotifier extends StateNotifier<SearchState> {
  SearchNotifier(this._ref) : super(const SearchState());

  final Ref _ref;

  /// Execute a search with the given query, using current filters.
  Future<void> search(String? query) async {
    final filters = state.filters.copyWith(query: query, clearQuery: query == null);
    state = state.copyWith(
      filters: filters,
      isLoading: true,
      offset: 0,
      clearError: true,
    );
    await _doSearch(refresh: true);
  }

  /// Apply new filters and re-search.
  Future<void> applyFilters(SearchFilters filters) async {
    state = state.copyWith(
      filters: filters.copyWith(query: state.filters.query),
      isLoading: true,
      offset: 0,
      clearError: true,
    );
    await _doSearch(refresh: true);
  }

  /// Reset all filters and re-search if there is a query.
  Future<void> resetFilters() async {
    final query = state.filters.query;
    state = state.copyWith(
      filters: SearchFilters(query: query),
      isLoading: query != null && query.isNotEmpty,
      offset: 0,
      clearError: true,
    );
    if (query != null && query.isNotEmpty) {
      await _doSearch(refresh: true);
    } else {
      state = state.copyWith(results: [], total: 0, hasMore: false);
    }
  }

  /// Load more results (pagination).
  Future<void> loadMore() async {
    if (state.isLoading || !state.hasMore) return;
    state = state.copyWith(isLoading: true, clearError: true);
    await _doSearch(refresh: false);
  }

  Future<void> _doSearch({required bool refresh}) async {
    final filters = state.filters;
    final offset = refresh ? 0 : state.offset;

    try {
      final api = _ref.read(apiClientProvider);
      final body = <String, dynamic>{
        'limit': _pageSize,
        'offset': offset,
        'sort': filters.sort,
        if (filters.query != null && filters.query!.isNotEmpty)
          'q': filters.query,
        if (filters.categoryId != null) 'category_id': filters.categoryId,
        if (filters.condition != null) 'condition': filters.condition,
        if (filters.priceMin != null) 'price_min': filters.priceMin,
        if (filters.priceMax != null) 'price_max': filters.priceMax,
        if (filters.isCertified == true) 'is_certified': true,
      };

      final resp = await api.post('/search/listings', data: body);
      final data = resp.data as Map<String, dynamic>;
      final items = (data['items'] as List)
          .map((e) => ListingSummary.fromJson(e as Map<String, dynamic>))
          .toList();
      final total = data['total'] as int? ?? items.length;

      if (!mounted) return;

      final newResults = refresh ? items : [...state.results, ...items];
      state = state.copyWith(
        results: newResults,
        isLoading: false,
        total: total,
        hasMore: newResults.length < total,
        offset: offset + items.length,
      );
    } catch (e) {
      if (!mounted) return;
      state = state.copyWith(
        isLoading: false,
        error: e.toString(),
      );
    }
  }
}
