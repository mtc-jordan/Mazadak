import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/core_providers.dart';
import '../../core/providers/listings_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';

// ═══════════════════════════════════════════════════════════════════
// Search state
// ═══════════════════════════════════════════════════════════════════

class _SearchFilters {
  const _SearchFilters({
    this.category,
    this.condition,
    this.priceMin = 0,
    this.priceMax = 10000,
    this.status,
    this.location,
    this.certifiedOnly = false,
  });

  final String? category;
  final String? condition;
  final double priceMin;
  final double priceMax;
  final String? status;
  final String? location;
  final bool certifiedOnly;

  bool get isActive =>
      category != null ||
      condition != null ||
      priceMin > 0 ||
      priceMax < 10000 ||
      status != null ||
      location != null ||
      certifiedOnly;

  _SearchFilters copyWith({
    String? category,
    String? condition,
    double? priceMin,
    double? priceMax,
    String? status,
    String? location,
    bool? certifiedOnly,
    bool clearCategory = false,
    bool clearCondition = false,
    bool clearStatus = false,
    bool clearLocation = false,
  }) {
    return _SearchFilters(
      category: clearCategory ? null : (category ?? this.category),
      condition: clearCondition ? null : (condition ?? this.condition),
      priceMin: priceMin ?? this.priceMin,
      priceMax: priceMax ?? this.priceMax,
      status: clearStatus ? null : (status ?? this.status),
      location: clearLocation ? null : (location ?? this.location),
      certifiedOnly: certifiedOnly ?? this.certifiedOnly,
    );
  }

  static const empty = _SearchFilters();
}

// ═══════════════════════════════════════════════════════════════════
// Search Screen
// ═══════════════════════════════════════════════════════════════════

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _searchController = TextEditingController();
  final _focusNode = FocusNode();
  Timer? _debounce;

  List<ListingSummary> _results = [];
  bool _isSearching = false;
  bool _hasSearched = false;
  _SearchFilters _filters = _SearchFilters.empty;
  String _sortBy = 'ends_asc';

  // Recent searches — persisted via SharedPreferences
  List<String> _recentSearches = [];

  static const _fog = Color(0xFFF5F2EC);
  static const _sortOptions = [
    (key: 'ends_asc', label: 'Ending soon'),
    (key: 'price_asc', label: 'Lowest price'),
    (key: 'bids_desc', label: 'Most bids'),
    (key: 'created_desc', label: 'Newest'),
  ];
  static const _recentSearchesKey = 'mzadak_recent_searches';

  static const _trendingChips = [
    'آيفون',
    'Rolex',
    'PS5',
    'Camera',
    'Gold',
    'Mercedes',
  ];

  @override
  void initState() {
    super.initState();
    _searchController.addListener(_onSearchChanged);
    _loadRecentSearches();
    // Auto-focus on mount
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _focusNode.requestFocus();
    });
  }

  Future<void> _loadRecentSearches() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getStringList(_recentSearchesKey);
    if (saved != null && mounted) {
      setState(() => _recentSearches = saved);
    }
  }

  Future<void> _saveRecentSearches() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_recentSearchesKey, _recentSearches);
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _searchController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _onSearchChanged() {
    setState(() {});
    _debounce?.cancel();
    if (_searchController.text.trim().isEmpty) {
      setState(() {
        _hasSearched = false;
        _results = [];
      });
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 300), _performSearch);
  }

  Future<void> _performSearch() async {
    final query = _searchController.text.trim();
    if (query.isEmpty) return;

    setState(() => _isSearching = true);

    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.get('/search/listings', queryParameters: {
        'q': query,
        'sort': _sortBy,
        if (_filters.category != null) 'category': _filters.category,
        if (_filters.condition != null) 'condition': _filters.condition,
        if (_filters.priceMin > 0) 'price_min': _filters.priceMin,
        if (_filters.priceMax < 10000) 'price_max': _filters.priceMax,
        if (_filters.status != null) 'status': _filters.status,
        if (_filters.location != null) 'location': _filters.location,
        if (_filters.certifiedOnly) 'certified': true,
      });

      final data = resp.data as Map<String, dynamic>;
      final items = (data['items'] as List)
          .map((e) => ListingSummary.fromJson(e as Map<String, dynamic>))
          .toList();

      if (!mounted) return;
      setState(() {
        _results = items;
        _isSearching = false;
        _hasSearched = true;
      });

      // Add to recent and persist
      if (!_recentSearches.contains(query)) {
        _recentSearches.insert(0, query);
        if (_recentSearches.length > 5) _recentSearches.removeLast();
        _saveRecentSearches();
      }
    } catch (_) {
      if (!mounted) return;
      // Fallback to mock filtered results when backend is unavailable
      final mockResults = _mockSearchResults
          .where((l) =>
              (l.titleAr.contains(query)) ||
              (l.titleEn?.toLowerCase().contains(query.toLowerCase()) ?? false))
          .toList();
      setState(() {
        _results = mockResults.isNotEmpty ? mockResults : _mockSearchResults;
        _isSearching = false;
        _hasSearched = true;
      });
    }
  }

  void _onSortChanged(String key) {
    if (_sortBy == key) return;
    setState(() => _sortBy = key);
    if (_hasSearched) _performSearch();
  }

  void _onSearchSubmitted(String text) {
    _debounce?.cancel();
    _performSearch();
  }

  void _onChipTap(String text) {
    _searchController.text = text;
    _searchController.selection =
        TextSelection.collapsed(offset: text.length);
    _debounce?.cancel();
    _performSearch();
  }

  void _removeRecent(int index) {
    setState(() => _recentSearches.removeAt(index));
    _saveRecentSearches();
  }

  void _openFilterSheet() async {
    final result = await showModalBottomSheet<_SearchFilters>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => _FilterSheet(
        filters: _filters,
      ),
    );
    if (result != null && mounted) {
      setState(() => _filters = result);
      if (_hasSearched) _performSearch();
    }
  }

  @override
  Widget build(BuildContext context) {
    final hasText = _searchController.text.isNotEmpty;

    return Scaffold(
      backgroundColor: _fog,
      body: SafeArea(
        child: Column(
          children: [
            // ── Search bar area ──────────────────────────────────
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
              child: Column(
                children: [
                  // Search bar with Hero
                  Row(
                    children: [
                      // Back button
                      GestureDetector(
                        onTap: () => context.pop(),
                        child: const Padding(
                          padding: EdgeInsets.only(right: 8),
                          child: Icon(
                            Icons.arrow_back_rounded,
                            color: AppColors.navy,
                            size: 24,
                          ),
                        ),
                      ),
                      Expanded(
                        child: Hero(
                          tag: 'search-bar',
                          child: Material(
                            color: Colors.transparent,
                            child: _buildSearchField(hasText),
                          ),
                        ),
                      ),
                    ],
                  ),

                  // Result count
                  if (_hasSearched && !_isSearching) ...[
                    const SizedBox(height: 8),
                    Align(
                      alignment: AlignmentDirectional.centerStart,
                      child: Text(
                        '${ArabicNumerals.formatNumber(_results.length)} نتيجة'
                        '${_searchController.text.isNotEmpty ? " لـ '${_searchController.text}'" : ''}',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.mist,
                        ),
                      ),
                    ),
                  ],

                  // Sort chips
                  if (_hasSearched) ...[
                    const SizedBox(height: 8),
                    _SortChips(
                      options: _sortOptions,
                      selected: _sortBy,
                      onSelected: _onSortChanged,
                    ),
                  ],
                ],
              ),
            ),

            const SizedBox(height: 8),

            // ── Body: suggestions or results ─────────────────────
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                child: _isSearching
                    ? _buildLoading()
                    : _hasSearched
                        ? _results.isEmpty
                            ? _buildEmptyState()
                            : _buildResults()
                        : _buildSuggestions(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSearchField(bool hasText) {
    return Container(
      height: 44,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: _focusNode.hasFocus ? AppColors.navy : AppColors.sand,
          width: _focusNode.hasFocus ? 1.5 : 0.5,
        ),
      ),
      child: TextField(
        controller: _searchController,
        focusNode: _focusNode,
        textInputAction: TextInputAction.search,
        onSubmitted: _onSearchSubmitted,
        style: const TextStyle(
          fontSize: 14,
          fontWeight: FontWeight.w500,
          color: AppColors.navy,
        ),
        decoration: InputDecoration(
          border: InputBorder.none,
          contentPadding:
              const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          hintText: 'Search auctions... ابحث',
          hintStyle: const TextStyle(
            fontSize: 13,
            color: AppColors.mist,
          ),
          prefixIcon: const Padding(
            padding: EdgeInsets.only(left: 12, right: 4),
            child:
                Icon(Icons.search_rounded, color: AppColors.navy, size: 20),
          ),
          prefixIconConstraints: const BoxConstraints(minWidth: 0),
          suffixIcon: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (hasText)
                GestureDetector(
                  onTap: () => _searchController.clear(),
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 4),
                    child: Icon(Icons.close_rounded,
                        color: AppColors.mist, size: 18),
                  ),
                ),
              GestureDetector(
                onTap: _openFilterSheet,
                child: Padding(
                  padding: const EdgeInsets.only(right: 12, left: 4),
                  child: Stack(
                    clipBehavior: Clip.none,
                    children: [
                      const Icon(Icons.tune_rounded,
                          color: AppColors.navy, size: 18),
                      if (_filters.isActive)
                        Positioned(
                          top: -2,
                          right: -2,
                          child: Container(
                            width: 7,
                            height: 7,
                            decoration: const BoxDecoration(
                              color: AppColors.gold,
                              shape: BoxShape.circle,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  // ── Suggestions ─────────────────────────────────────────────────

  Widget _buildSuggestions() {
    return ListView(
      key: const ValueKey('suggestions'),
      padding: const EdgeInsets.symmetric(horizontal: 16),
      children: [
        // Recent searches
        if (_recentSearches.isNotEmpty) ...[
          const SizedBox(height: 12),
          const Text(
            'Recent searches',
            style: TextStyle(
              fontFamily: 'Sora',
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: 8),
          ...List.generate(_recentSearches.length, (i) {
            return InkWell(
              onTap: () => _onChipTap(_recentSearches[i]),
              borderRadius: BorderRadius.circular(8),
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 10),
                child: Row(
                  children: [
                    const Icon(Icons.schedule_rounded,
                        size: 16, color: AppColors.mist),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _recentSearches[i],
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.ink,
                        ),
                      ),
                    ),
                    GestureDetector(
                      onTap: () => _removeRecent(i),
                      child: const Icon(Icons.close_rounded,
                          size: 16, color: AppColors.mist),
                    ),
                  ],
                ),
              ),
            );
          }),
        ],

        // Trending
        const SizedBox(height: 24),
        const Text(
          'Trending now',
          style: TextStyle(
            fontFamily: 'Sora',
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: _trendingChips.map((chip) {
            return GestureDetector(
              onTap: () => _onChipTap(chip),
              child: Container(
                height: 34,
                padding: const EdgeInsets.symmetric(horizontal: 14),
                decoration: BoxDecoration(
                  color: AppColors.cream,
                  borderRadius: BorderRadius.circular(20),
                ),
                alignment: Alignment.center,
                child: Text(
                  chip,
                  style: const TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: AppColors.gold,
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  // ── Results ─────────────────────────────────────────────────────

  Widget _buildResults() {
    return ListView.builder(
      key: const ValueKey('results'),
      padding: const EdgeInsets.symmetric(horizontal: 16),
      itemCount: _results.length,
      itemBuilder: (_, i) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: _WideResultCardAnimated(listing: _results[i], index: i),
      ),
    );
  }

  // ── Loading ─────────────────────────────────────────────────────

  Widget _buildLoading() {
    return const Center(
      key: ValueKey('loading'),
      child: Padding(
        padding: EdgeInsets.only(bottom: 40),
        child: SizedBox(
          width: 28,
          height: 28,
          child: CircularProgressIndicator(
            strokeWidth: 2.5,
            color: AppColors.gold,
          ),
        ),
      ),
    );
  }

  // ── Empty state ─────────────────────────────────────────────────

  Widget _buildEmptyState() {
    return Center(
      key: const ValueKey('empty'),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.search_off_rounded,
              size: 56, color: AppColors.mist.withOpacity(0.4)),
          const SizedBox(height: 16),
          const Text(
            'No results · لا توجد نتائج',
            style: TextStyle(
              fontFamily: 'Sora',
              fontSize: 16,
              fontWeight: FontWeight.w700,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Try a different search or adjust filters',
            style: TextStyle(fontSize: 13, color: AppColors.mist),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Sort Chips
// ═══════════════════════════════════════════════════════════════════

class _SortChips extends StatelessWidget {
  const _SortChips({
    required this.options,
    required this.selected,
    required this.onSelected,
  });

  final List<({String key, String label})> options;
  final String selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 32,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: options.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final opt = options[i];
          final isActive = opt.key == selected;
          return GestureDetector(
            onTap: () => onSelected(opt.key),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: isActive ? AppColors.navy : Colors.white,
                borderRadius: BorderRadius.circular(16),
                border: isActive
                    ? null
                    : Border.all(color: AppColors.sand, width: 0.5),
              ),
              alignment: Alignment.center,
              child: Text(
                opt.label,
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 10,
                  fontWeight: FontWeight.w600,
                  color: isActive ? Colors.white : AppColors.navy,
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Wide Result Card with stagger entrance
// ═══════════════════════════════════════════════════════════════════

class _WideResultCardAnimated extends StatefulWidget {
  const _WideResultCardAnimated({
    required this.listing,
    required this.index,
  });

  final ListingSummary listing;
  final int index;

  @override
  State<_WideResultCardAnimated> createState() =>
      _WideResultCardAnimatedState();
}

class _WideResultCardAnimatedState extends State<_WideResultCardAnimated>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _fade;
  late final Animation<Offset> _slide;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _fade = CurvedAnimation(parent: _controller, curve: Curves.easeOut);
    _slide = Tween<Offset>(
      begin: const Offset(0, 0.08),
      end: Offset.zero,
    ).animate(
        CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic));

    Future.delayed(Duration(milliseconds: 50 * widget.index), () {
      if (mounted) _controller.forward();
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _fade,
      child: SlideTransition(
        position: _slide,
        child: _WideResultCard(listing: widget.listing),
      ),
    );
  }
}

class _WideResultCard extends StatelessWidget {
  const _WideResultCard({required this.listing});
  final ListingSummary listing;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/listing/${listing.id}'),
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.sand, width: 0.5),
        ),
        child: Row(
          children: [
            // Thumbnail
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: SizedBox(
                width: 64,
                height: 64,
                child: CachedNetworkImage(
                  imageUrl: listing.imageUrl,
                  fit: BoxFit.cover,
                  placeholder: (_, __) => Container(color: AppColors.sand),
                  errorWidget: (_, __, ___) => Container(
                    color: AppColors.sand,
                    child: const Icon(Icons.image_rounded,
                        color: AppColors.mist, size: 24),
                  ),
                ),
              ),
            ),
            const SizedBox(width: 12),

            // Info
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    listing.titleEn ?? listing.titleAr,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                      height: 1.2,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (listing.titleEn != null) ...[
                    const SizedBox(height: 1),
                    Text(
                      listing.titleAr,
                      style: const TextStyle(
                        fontFamily: 'NotoKufiArabic',
                        fontSize: 11,
                        color: AppColors.mist,
                        height: 1.2,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                  const SizedBox(height: 4),
                  Text(
                    ArabicNumerals.formatCurrency(
                      listing.displayPrice,
                      listing.currency,
                    ),
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                      color: AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Row(
                    children: [
                      Text(
                        '${ArabicNumerals.formatNumber(listing.bidCount)} bids',
                        style: const TextStyle(
                          fontSize: 10,
                          color: AppColors.mist,
                        ),
                      ),
                      if (listing.endsAt != null) ...[
                        const SizedBox(width: 8),
                        const Icon(Icons.timer_rounded,
                            size: 10, color: AppColors.mist),
                        const SizedBox(width: 2),
                        Text(
                          _timeLeft,
                          style: const TextStyle(
                            fontSize: 10,
                            color: AppColors.mist,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),

            // Category badge
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.cream,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                listing.condition,
                style: const TextStyle(
                  fontSize: 9,
                  fontWeight: FontWeight.w600,
                  color: AppColors.gold,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String get _timeLeft {
    if (listing.endsAt == null) return '';
    final end = DateTime.tryParse(listing.endsAt!);
    if (end == null) return '';
    final diff = end.difference(DateTime.now().toUtc());
    if (diff.isNegative) return 'Ended';
    if (diff.inDays > 0) return '${diff.inDays}d';
    if (diff.inHours > 0) return '${diff.inHours}h';
    return '${diff.inMinutes}m';
  }
}

// ═══════════════════════════════════════════════════════════════════
// Mock search results (dev fallback when backend is unavailable)
// ═══════════════════════════════════════════════════════════════════

final _mockSearchResults = [
  ListingSummary(
    id: 'search-1',
    titleAr: 'آيفون ١٥ برو ماكس ٢٥٦ جيجا',
    titleEn: 'iPhone 15 Pro Max 256GB',
    imageUrl: 'https://picsum.photos/seed/iphone15/400/300',
    startingPrice: 350,
    currentPrice: 520,
    currency: 'JOD',
    condition: 'Like New',
    status: 'active',
    bidCount: 14,
    endsAt: DateTime.now().toUtc().add(const Duration(hours: 2)).toIso8601String(),
  ),
  ListingSummary(
    id: 'search-2',
    titleAr: 'ساعة رولكس سبمارينر',
    titleEn: 'Rolex Submariner',
    imageUrl: 'https://picsum.photos/seed/rolex2/400/300',
    startingPrice: 8500,
    currentPrice: 12750,
    currency: 'JOD',
    condition: 'New',
    status: 'active',
    bidCount: 23,
    endsAt: DateTime.now().toUtc().add(const Duration(hours: 5)).toIso8601String(),
    isCertified: true,
  ),
  ListingSummary(
    id: 'search-3',
    titleAr: 'بلايستيشن ٥ مع ألعاب',
    titleEn: 'PlayStation 5 Bundle',
    imageUrl: 'https://picsum.photos/seed/ps5s/400/300',
    startingPrice: 180,
    currentPrice: 245,
    currency: 'JOD',
    condition: 'Used',
    status: 'active',
    bidCount: 11,
    endsAt: DateTime.now().toUtc().add(const Duration(minutes: 45)).toIso8601String(),
  ),
  ListingSummary(
    id: 'search-4',
    titleAr: 'كاميرا كانون EOS R5',
    titleEn: 'Canon EOS R5 Camera',
    imageUrl: 'https://picsum.photos/seed/canon/400/300',
    startingPrice: 1200,
    currentPrice: 1800,
    currency: 'JOD',
    condition: 'Excellent',
    status: 'active',
    bidCount: 7,
    endsAt: DateTime.now().toUtc().add(const Duration(days: 1)).toIso8601String(),
  ),
  ListingSummary(
    id: 'search-5',
    titleAr: 'سوار ذهب عيار ٢١',
    titleEn: 'Gold Bracelet 21K',
    imageUrl: 'https://picsum.photos/seed/gold2/400/300',
    startingPrice: 400,
    currentPrice: 650,
    currency: 'JOD',
    condition: 'New',
    status: 'active',
    bidCount: 19,
    endsAt: DateTime.now().toUtc().add(const Duration(hours: 8)).toIso8601String(),
    isCertified: true,
  ),
];

// ═══════════════════════════════════════════════════════════════════
// Filter Bottom Sheet
// ═══════════════════════════════════════════════════════════════════

class _FilterSheet extends StatefulWidget {
  const _FilterSheet({
    required this.filters,
  });

  final _SearchFilters filters;

  @override
  State<_FilterSheet> createState() => _FilterSheetState();
}

class _FilterSheetState extends State<_FilterSheet> {
  late _SearchFilters _draft;

  static const _categories = [
    'All',
    'Electronics',
    'Vehicles',
    'Jewelry',
    'Art',
    'Fashion',
    'Antiques',
    'Charity',
  ];
  static const _conditions = ['Brand New', 'Like New', 'Very Good', 'Good'];
  static const _statuses = [
    'Live Now',
    'Ending Soon',
    'Buy It Now',
    'Charity'
  ];
  static const _locations = ['Jordan', 'Saudi Arabia', 'UAE', 'All GCC'];

  @override
  void initState() {
    super.initState();
    _draft = widget.filters;
  }

  @override
  Widget build(BuildContext context) {
    return DraggableScrollableSheet(
      initialChildSize: 0.6,
      maxChildSize: 0.92,
      minChildSize: 0.4,
      builder: (_, scrollController) {
        return Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
          ),
          child: ListView(
            controller: scrollController,
            padding: const EdgeInsets.symmetric(horizontal: 20),
            children: [
              const SizedBox(height: 12),
              // Handle bar
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.cream,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 20),

              const Text(
                'Filters',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: 20),

              // Category
              _FilterSection(
                title: 'Category',
                child: _ChipGrid(
                  items: _categories,
                  selected: _draft.category,
                  onSelected: (v) => setState(() {
                    _draft = v == 'All' || v == _draft.category
                        ? _draft.copyWith(clearCategory: true)
                        : _draft.copyWith(category: v);
                  }),
                ),
              ),

              // Condition
              _FilterSection(
                title: 'Condition',
                child: _ChipGrid(
                  items: _conditions,
                  selected: _draft.condition,
                  onSelected: (v) => setState(() {
                    _draft = v == _draft.condition
                        ? _draft.copyWith(clearCondition: true)
                        : _draft.copyWith(condition: v);
                  }),
                ),
              ),

              // Price range
              _FilterSection(
                title: 'Price range',
                child: Column(
                  children: [
                    RangeSlider(
                      values:
                          RangeValues(_draft.priceMin, _draft.priceMax),
                      min: 0,
                      max: 10000,
                      divisions: 100,
                      activeColor: AppColors.navy,
                      inactiveColor: AppColors.sand,
                      onChanged: (v) => setState(() {
                        _draft = _draft.copyWith(
                          priceMin: v.start,
                          priceMax: v.end,
                        );
                      }),
                    ),
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(
                            '${_draft.priceMin.toInt()} JOD',
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: AppColors.navy,
                            ),
                          ),
                          Text(
                            '${_draft.priceMax.toInt()} JOD',
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: AppColors.navy,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),

              // Status
              _FilterSection(
                title: 'Status',
                child: _ChipGrid(
                  items: _statuses,
                  selected: _draft.status,
                  onSelected: (v) => setState(() {
                    _draft = v == _draft.status
                        ? _draft.copyWith(clearStatus: true)
                        : _draft.copyWith(status: v);
                  }),
                ),
              ),

              // Location
              _FilterSection(
                title: 'Location',
                child: _ChipGrid(
                  items: _locations,
                  selected: _draft.location,
                  onSelected: (v) => setState(() {
                    _draft = v == _draft.location
                        ? _draft.copyWith(clearLocation: true)
                        : _draft.copyWith(location: v);
                  }),
                ),
              ),

              // Certified only
              Padding(
                padding: const EdgeInsets.only(top: 8, bottom: 16),
                child: Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Certified only',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppColors.navy,
                        ),
                      ),
                    ),
                    Switch.adaptive(
                      value: _draft.certifiedOnly,
                      activeColor: AppColors.emerald,
                      onChanged: (v) => setState(() {
                        _draft = _draft.copyWith(certifiedOnly: v);
                      }),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 8),

              // Action buttons
              Row(
                children: [
                  Expanded(
                    child: SizedBox(
                      height: 48,
                      child: OutlinedButton(
                        onPressed: () => setState(() {
                          _draft = _SearchFilters.empty;
                        }),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppColors.navy,
                          side: const BorderSide(
                              color: AppColors.navy, width: 1.5),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          textStyle: const TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        child: const Text('Clear all'),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: SizedBox(
                      height: 48,
                      child: ElevatedButton(
                        onPressed: () => Navigator.pop(context, _draft),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.navy,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12),
                          ),
                          elevation: 0,
                          textStyle: const TextStyle(
                            fontFamily: 'Sora',
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        child: const Text('Apply filters'),
                      ),
                    ),
                  ),
                ],
              ),
              SizedBox(height: MediaQuery.of(context).padding.bottom + 16),
            ],
          ),
        );
      },
    );
  }
}

class _FilterSection extends StatelessWidget {
  const _FilterSection({required this.title, required this.child});
  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }
}

class _ChipGrid extends StatelessWidget {
  const _ChipGrid({
    required this.items,
    required this.selected,
    required this.onSelected,
  });

  final List<String> items;
  final String? selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      children: items.map((item) {
        final isActive = item == selected;
        return GestureDetector(
          onTap: () => onSelected(item),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: isActive ? AppColors.navy : Colors.white,
              borderRadius: BorderRadius.circular(20),
              border: isActive
                  ? null
                  : Border.all(color: AppColors.sand, width: 1),
            ),
            child: Text(
              item,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                color: isActive ? Colors.white : AppColors.navy,
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}
