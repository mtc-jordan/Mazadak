import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../core/providers/create_listing_provider.dart';
import '../../core/providers/search_provider.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';

// ═══════════════════════════════════════════════════════════════════
// Sort option model
// ═══════════════════════════════════════════════════════════════════

class _SortOption {
  const _SortOption(this.value, this.labelAr);
  final String value;
  final String labelAr;
}

const _sortOptions = [
  _SortOption('ends_asc', 'الأقرب انتهاءً'),
  _SortOption('price_asc', 'الأقل سعراً'),
  _SortOption('bid_count_desc', 'الأكثر مزايدة'),
];

// ═══════════════════════════════════════════════════════════════════
// Show helper
// ═══════════════════════════════════════════════════════════════════

/// Shows the search-filters bottom sheet and returns the selected filters,
/// or null if dismissed.
Future<SearchFilters?> showSearchFiltersSheet(
  BuildContext context, {
  required SearchFilters currentFilters,
}) {
  return showModalBottomSheet<SearchFilters>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (_) => SearchFiltersSheet(filters: currentFilters),
  );
}

// ═══════════════════════════════════════════════════════════════════
// Filter Sheet Widget
// ═══════════════════════════════════════════════════════════════════

class SearchFiltersSheet extends StatefulWidget {
  const SearchFiltersSheet({super.key, required this.filters});

  final SearchFilters filters;

  @override
  State<SearchFiltersSheet> createState() => _SearchFiltersSheetState();
}

class _SearchFiltersSheetState extends State<SearchFiltersSheet> {
  late SearchFilters _draft;
  final _priceMinController = TextEditingController();
  final _priceMaxController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _draft = widget.filters;
    // Convert cents to JOD for display
    if (_draft.priceMin != null) {
      _priceMinController.text = (_draft.priceMin! / 100).toStringAsFixed(0);
    }
    if (_draft.priceMax != null) {
      _priceMaxController.text = (_draft.priceMax! / 100).toStringAsFixed(0);
    }
  }

  @override
  void dispose() {
    _priceMinController.dispose();
    _priceMaxController.dispose();
    super.dispose();
  }

  void _onReset() {
    HapticFeedback.lightImpact();
    setState(() {
      _draft = SearchFilters(query: _draft.query);
      _priceMinController.clear();
      _priceMaxController.clear();
    });
  }

  void _onApply() {
    HapticFeedback.mediumImpact();
    // Parse price fields (JOD -> cents)
    final minText = _priceMinController.text.trim();
    final maxText = _priceMaxController.text.trim();
    final minParsed = minText.isNotEmpty ? int.tryParse(minText) : null;
    final maxParsed = maxText.isNotEmpty ? int.tryParse(maxText) : null;
    final priceMin = minParsed != null ? minParsed * 100 : null;
    final priceMax = maxParsed != null ? maxParsed * 100 : null;

    final filters = _draft.copyWith(
      priceMin: priceMin,
      priceMax: priceMax,
      clearPriceMin: priceMin == null,
      clearPriceMax: priceMax == null,
    );
    Navigator.pop(context, filters);
  }

  @override
  Widget build(BuildContext context) {
    final bottomPadding = MediaQuery.of(context).padding.bottom;

    return DraggableScrollableSheet(
      initialChildSize: 0.72,
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
            padding: const EdgeInsetsDirectional.symmetric(horizontal: 20),
            children: [
              const SizedBox(height: 12),
              // Handle bar
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    color: AppColors.sand,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              const SizedBox(height: 20),

              // Title row
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'تصفية البحث',
                      style: TextStyle(
                        fontFamily: 'NotoKufiArabic',
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                      ),
                    ),
                  ),
                  if (_draft.hasActiveFilters)
                    GestureDetector(
                      onTap: _onReset,
                      child: const Text(
                        'إعادة تعيين',
                        style: TextStyle(
                          fontFamily: 'NotoKufiArabic',
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: AppColors.gold,
                        ),
                      ),
                    ),
                ],
              ),
              const SizedBox(height: AppSpacing.lg),

              // ── Category ──────────────────────────────────────
              _buildSectionLabel('الفئة'),
              const SizedBox(height: AppSpacing.xs),
              SizedBox(
                height: 42,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: kCategories.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) {
                    final cat = kCategories[i];
                    final isActive = _draft.categoryId == cat.id;
                    return GestureDetector(
                      onTap: () {
                        HapticFeedback.selectionClick();
                        setState(() {
                          _draft = isActive
                              ? _draft.copyWith(clearCategory: true)
                              : _draft.copyWith(categoryId: cat.id);
                        });
                      },
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 200),
                        padding: const EdgeInsetsDirectional.symmetric(
                            horizontal: 14),
                        decoration: BoxDecoration(
                          color: isActive ? AppColors.navy : Colors.white,
                          borderRadius: AppSpacing.radiusFull,
                          border: isActive
                              ? null
                              : Border.all(color: AppColors.sand, width: 1),
                        ),
                        alignment: Alignment.center,
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(cat.icon, style: const TextStyle(fontSize: 14)),
                            const SizedBox(width: 6),
                            Text(
                              cat.nameAr,
                              style: TextStyle(
                                fontFamily: 'NotoKufiArabic',
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                                color:
                                    isActive ? Colors.white : AppColors.navy,
                              ),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(height: AppSpacing.lg),

              // ── Condition ─────────────────────────────────────
              _buildSectionLabel('الحالة'),
              const SizedBox(height: AppSpacing.xs),
              SizedBox(
                height: 38,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: kConditions.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 8),
                  itemBuilder: (_, i) {
                    final cond = kConditions[i];
                    final isActive = _draft.condition == cond.value;
                    return GestureDetector(
                      onTap: () {
                        HapticFeedback.selectionClick();
                        setState(() {
                          _draft = isActive
                              ? _draft.copyWith(clearCondition: true)
                              : _draft.copyWith(condition: cond.value);
                        });
                      },
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 200),
                        padding: const EdgeInsetsDirectional.symmetric(
                            horizontal: 14),
                        decoration: BoxDecoration(
                          color: isActive ? AppColors.navy : Colors.white,
                          borderRadius: AppSpacing.radiusFull,
                          border: isActive
                              ? null
                              : Border.all(color: AppColors.sand, width: 1),
                        ),
                        alignment: Alignment.center,
                        child: Text(
                          cond.labelAr,
                          style: TextStyle(
                            fontFamily: 'NotoKufiArabic',
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: isActive ? Colors.white : AppColors.navy,
                          ),
                        ),
                      ),
                    );
                  },
                ),
              ),
              const SizedBox(height: AppSpacing.lg),

              // ── Price Range ───────────────────────────────────
              _buildSectionLabel('نطاق السعر (د.أ)'),
              const SizedBox(height: AppSpacing.xs),
              Row(
                children: [
                  Expanded(
                    child: _PriceField(
                      controller: _priceMinController,
                      hint: 'الحد الأدنى',
                    ),
                  ),
                  const Padding(
                    padding: EdgeInsetsDirectional.symmetric(horizontal: 12),
                    child: Text(
                      '—',
                      style: TextStyle(
                        fontSize: 16,
                        color: AppColors.mist,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  Expanded(
                    child: _PriceField(
                      controller: _priceMaxController,
                      hint: 'الحد الأقصى',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.lg),

              // ── Sort ──────────────────────────────────────────
              _buildSectionLabel('الترتيب'),
              const SizedBox(height: AppSpacing.xs),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: _sortOptions.map((opt) {
                  final isActive = _draft.sort == opt.value;
                  return GestureDetector(
                    onTap: () {
                      HapticFeedback.selectionClick();
                      setState(() {
                        _draft = _draft.copyWith(sort: opt.value);
                      });
                    },
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 200),
                      padding: const EdgeInsetsDirectional.symmetric(
                          horizontal: 14, vertical: 8),
                      decoration: BoxDecoration(
                        color: isActive ? AppColors.navy : Colors.white,
                        borderRadius: AppSpacing.radiusFull,
                        border: isActive
                            ? null
                            : Border.all(color: AppColors.sand, width: 1),
                      ),
                      child: Text(
                        opt.labelAr,
                        style: TextStyle(
                          fontFamily: 'NotoKufiArabic',
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: isActive ? Colors.white : AppColors.navy,
                        ),
                      ),
                    ),
                  );
                }).toList(),
              ),
              const SizedBox(height: AppSpacing.lg),

              // ── Certified Only ────────────────────────────────
              Container(
                padding: const EdgeInsetsDirectional.symmetric(
                    horizontal: 14, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.cream,
                  borderRadius: AppSpacing.radiusMd,
                ),
                child: Row(
                  children: [
                    const Icon(Icons.verified_rounded,
                        size: 18, color: AppColors.gold),
                    const SizedBox(width: 8),
                    const Expanded(
                      child: Text(
                        'موثّق فقط',
                        style: TextStyle(
                          fontFamily: 'NotoKufiArabic',
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.navy,
                        ),
                      ),
                    ),
                    Switch.adaptive(
                      value: _draft.isCertified == true,
                      activeColor: AppColors.gold,
                      onChanged: (v) {
                        HapticFeedback.selectionClick();
                        setState(() {
                          _draft = v
                              ? _draft.copyWith(isCertified: true)
                              : _draft.copyWith(clearCertified: true);
                        });
                      },
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpacing.xl),

              // ── Action Buttons ────────────────────────────────
              Row(
                children: [
                  // Reset button
                  Expanded(
                    child: SizedBox(
                      height: 48,
                      child: OutlinedButton(
                        onPressed: _onReset,
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppColors.navy,
                          side: const BorderSide(
                              color: AppColors.navy, width: 1.5),
                          shape: RoundedRectangleBorder(
                            borderRadius: AppSpacing.radiusMd,
                          ),
                          textStyle: const TextStyle(
                            fontFamily: 'NotoKufiArabic',
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        child: const Text('مسح الكل'),
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  // Apply button (gold)
                  Expanded(
                    flex: 2,
                    child: SizedBox(
                      height: 48,
                      child: ElevatedButton(
                        onPressed: _onApply,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppColors.gold,
                          foregroundColor: Colors.white,
                          shape: RoundedRectangleBorder(
                            borderRadius: AppSpacing.radiusMd,
                          ),
                          elevation: 0,
                          textStyle: const TextStyle(
                            fontFamily: 'NotoKufiArabic',
                            fontSize: 14,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        child: const Text('تطبيق الفلاتر'),
                      ),
                    ),
                  ),
                ],
              ),
              SizedBox(height: bottomPadding + 16),
            ],
          ),
        );
      },
    );
  }

  Widget _buildSectionLabel(String text) {
    return Text(
      text,
      style: const TextStyle(
        fontFamily: 'NotoKufiArabic',
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: AppColors.navy,
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Price Field
// ═══════════════════════════════════════════════════════════════════

class _PriceField extends StatelessWidget {
  const _PriceField({
    required this.controller,
    required this.hint,
  });

  final TextEditingController controller;
  final String hint;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      keyboardType: TextInputType.number,
      textAlign: TextAlign.center,
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      style: const TextStyle(
        fontFamily: 'Sora',
        fontSize: 14,
        fontWeight: FontWeight.w600,
        color: AppColors.navy,
      ),
      decoration: InputDecoration(
        hintText: hint,
        hintStyle: const TextStyle(
          fontFamily: 'NotoKufiArabic',
          fontSize: 11,
          color: AppColors.mist,
        ),
        filled: true,
        fillColor: AppColors.cream,
        contentPadding:
            const EdgeInsetsDirectional.symmetric(horizontal: 12, vertical: 12),
        border: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: AppSpacing.radiusMd,
          borderSide: const BorderSide(color: AppColors.navy, width: 1.5),
        ),
        suffixText: 'د.أ',
        suffixStyle: const TextStyle(
          fontFamily: 'NotoKufiArabic',
          fontSize: 11,
          color: AppColors.mist,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
