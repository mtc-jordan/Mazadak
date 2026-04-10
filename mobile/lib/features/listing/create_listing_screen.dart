import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/providers/create_listing_provider.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/haptics.dart';
import '../../core/theme/spacing.dart';

/// 5-step Create Listing wizard — SDD §5.3.
///
/// Steps: Photos → Details → Pricing → Schedule → Review & Publish.
class CreateListingScreen extends ConsumerStatefulWidget {
  const CreateListingScreen({super.key});

  @override
  ConsumerState<CreateListingScreen> createState() =>
      _CreateListingScreenState();
}

class _CreateListingScreenState extends ConsumerState<CreateListingScreen> {
  late final PageController _pageController;
  final _picker = ImagePicker();

  // Form keys per step
  final _detailsFormKey = GlobalKey<FormState>();
  final _pricingFormKey = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    _pageController = PageController();
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  void _goToStep(int step) {
    _pageController.animateToPage(
      step,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOutCubic,
    );
    ref.read(createListingProvider.notifier).goToStep(step);
  }

  void _next() {
    final s = ref.read(createListingProvider);
    final notifier = ref.read(createListingProvider.notifier);

    // Validate current step
    switch (s.currentStep) {
      case 0:
        if (!s.canProceedFromPhotos) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('أضف ٣ صور على الأقل'),
            backgroundColor: AppColors.ember,
          ));
          return;
        }
      case 1:
        if (!(_detailsFormKey.currentState?.validate() ?? false)) return;
        if (!s.canProceedFromDetails) return;
      case 2:
        if (!(_pricingFormKey.currentState?.validate() ?? false)) return;
        if (!s.canProceedFromPricing) return;
    }

    HapticFeedback.selectionClick();
    notifier.nextStep();
    _pageController.nextPage(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOutCubic,
    );
  }

  void _back() {
    ref.read(createListingProvider.notifier).previousStep();
    _pageController.previousPage(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOutCubic,
    );
  }

  @override
  Widget build(BuildContext context) {
    final s = ref.watch(createListingProvider);

    // After publishing, show success overlay
    if (s.publishedStatus != null) {
      return _SuccessScreen(status: s.publishedStatus!);
    }

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: AppColors.navy,
        leading: IconButton(
          icon: const Icon(Icons.close_rounded),
          onPressed: () => context.pop(),
        ),
        title: const Text(
          'إضافة منتج',
          style: TextStyle(fontWeight: FontWeight.w700, fontFamily: 'Sora'),
        ),
        centerTitle: true,
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(48),
          child: _StepIndicator(
            currentStep: s.currentStep,
            onTap: _goToStep,
          ),
        ),
      ),
      body: Column(
        children: [
          // ── Page content ────────────────────────────────────
          Expanded(
            child: PageView(
              controller: _pageController,
              physics: const NeverScrollableScrollPhysics(),
              children: [
                _PhotoStep(picker: _picker),
                _DetailsStep(formKey: _detailsFormKey),
                _PricingStep(formKey: _pricingFormKey),
                const _ScheduleStep(),
                _ReviewStep(onEditSection: _goToStep),
              ],
            ),
          ),

          // ── Error banner ────────────────────────────────────
          if (s.error != null)
            Container(
              width: double.infinity,
              margin: AppSpacing.horizontalMd,
              padding: AppSpacing.allSm,
              decoration: BoxDecoration(
                color: AppColors.ember.withOpacity(0.1),
                borderRadius: AppSpacing.radiusMd,
              ),
              child: Text(
                s.error!,
                style: const TextStyle(fontSize: 13, color: AppColors.ember),
                textAlign: TextAlign.center,
              ),
            ),

          // ── Bottom navigation bar ──────────────────────────
          SafeArea(
            child: Padding(
              padding: const EdgeInsetsDirectional.fromSTEB(16, 8, 16, 8),
              child: Row(
                children: [
                  if (s.currentStep > 0)
                    Expanded(
                      child: OutlinedButton(
                        onPressed: _back,
                        style: OutlinedButton.styleFrom(
                          foregroundColor: AppColors.navy,
                          side: const BorderSide(color: AppColors.sand),
                          padding: const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: AppSpacing.radiusMd,
                          ),
                        ),
                        child: const Text('السابق',
                            style: TextStyle(fontWeight: FontWeight.w600)),
                      ),
                    ),
                  if (s.currentStep > 0) const SizedBox(width: 12),
                  Expanded(
                    flex: 2,
                    child: s.currentStep == 4
                        ? _PublishButton()
                        : _NextButton(onPressed: _next),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Step Indicator ────────────────────────────────────────────

class _StepIndicator extends StatelessWidget {
  const _StepIndicator({required this.currentStep, required this.onTap});
  final int currentStep;
  final void Function(int) onTap;

  static const _labels = ['صور', 'تفاصيل', 'سعر', 'جدولة', 'نشر'];

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: AppSpacing.horizontalMd,
      child: Row(
        children: List.generate(5, (i) {
          final isActive = i == currentStep;
          final isDone = i < currentStep;
          return Expanded(
            child: GestureDetector(
              onTap: isDone ? () => onTap(i) : null,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    height: 4,
                    margin: const EdgeInsets.symmetric(horizontal: 2),
                    decoration: BoxDecoration(
                      color: isDone
                          ? AppColors.emerald
                          : isActive
                              ? AppColors.gold
                              : AppColors.sand,
                      borderRadius: AppSpacing.radiusFull,
                    ),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    _labels[i],
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: isActive ? FontWeight.w700 : FontWeight.w500,
                      color: isActive ? AppColors.navy : AppColors.mist,
                    ),
                  ),
                  const SizedBox(height: 4),
                ],
              ),
            ),
          );
        }),
      ),
    );
  }
}

// ── Step 1: Photos ────────────────────────────────────────────

class _PhotoStep extends ConsumerWidget {
  const _PhotoStep({required this.picker});
  final ImagePicker picker;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final photos = ref.watch(createListingProvider.select((s) => s.photos));
    final isUploading =
        ref.watch(createListingProvider.select((s) => s.isUploading));
    final progress =
        ref.watch(createListingProvider.select((s) => s.uploadProgress));

    return ListView(
      padding: AppSpacing.allMd,
      children: [
        // Header
        Text(
          'أضف صور المنتج',
          style: const TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 4),
        Text(
          '${photos.length}/20 صورة • الحد الأدنى ٣',
          style: const TextStyle(fontSize: 13, color: AppColors.mist),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: AppSpacing.lg),

        // Upload progress
        if (isUploading) ...[
          ClipRRect(
            borderRadius: AppSpacing.radiusFull,
            child: LinearProgressIndicator(
              value: progress,
              minHeight: 6,
              backgroundColor: AppColors.sand,
              valueColor: const AlwaysStoppedAnimation(AppColors.gold),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'جاري رفع الصور... ${(progress * 100).toInt()}%',
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 12, color: AppColors.mist),
          ),
          const SizedBox(height: AppSpacing.md),
        ],

        // Photo grid
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 3,
            crossAxisSpacing: 8,
            mainAxisSpacing: 8,
          ),
          itemCount: photos.length + (photos.length < 20 ? 1 : 0),
          itemBuilder: (ctx, i) {
            if (i == photos.length) {
              return _AddPhotoTile(
                onTap: () => _pickImages(context, ref),
              );
            }
            return _PhotoTile(
              photo: photos[i],
              isPrimary: i == 0,
              onRemove: () => ref
                  .read(createListingProvider.notifier)
                  .removePhoto(i),
            );
          },
        ),

        const SizedBox(height: AppSpacing.lg),

        // Action buttons
        Row(
          children: [
            Expanded(
              child: OutlinedButton.icon(
                icon: const Icon(Icons.camera_alt_rounded, size: 18),
                label: const Text('الكاميرا'),
                onPressed: () => _takePhoto(ref),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.navy,
                  side: const BorderSide(color: AppColors.sand),
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.radiusMd,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: OutlinedButton.icon(
                icon: const Icon(Icons.photo_library_rounded, size: 18),
                label: const Text('المعرض'),
                onPressed: () => _pickImages(context, ref),
                style: OutlinedButton.styleFrom(
                  foregroundColor: AppColors.navy,
                  side: const BorderSide(color: AppColors.sand),
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.radiusMd,
                  ),
                ),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Future<void> _pickImages(BuildContext context, WidgetRef ref) async {
    final images = await picker.pickMultiImage(imageQuality: 85);
    if (images.isNotEmpty) {
      ref.read(createListingProvider.notifier).addPhotos(images);
    }
  }

  Future<void> _takePhoto(WidgetRef ref) async {
    final image = await picker.pickImage(
      source: ImageSource.camera,
      imageQuality: 85,
    );
    if (image != null) {
      ref.read(createListingProvider.notifier).addPhotos([image]);
    }
  }
}

class _AddPhotoTile extends StatelessWidget {
  const _AddPhotoTile({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: AppColors.sand.withOpacity(0.5),
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(
            color: AppColors.mist.withOpacity(0.3),
            style: BorderStyle.solid,
          ),
        ),
        child: const Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.add_photo_alternate_rounded,
                size: 28, color: AppColors.mist),
            SizedBox(height: 4),
            Text('إضافة',
                style: TextStyle(fontSize: 11, color: AppColors.mist)),
          ],
        ),
      ),
    );
  }
}

class _PhotoTile extends StatelessWidget {
  const _PhotoTile({
    required this.photo,
    required this.isPrimary,
    required this.onRemove,
  });
  final XFile photo;
  final bool isPrimary;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        ClipRRect(
          borderRadius: AppSpacing.radiusMd,
          child: Image.network(
            photo.path,
            fit: BoxFit.cover,
            width: double.infinity,
            height: double.infinity,
            errorBuilder: (_, __, ___) => Container(
              color: AppColors.sand,
              child: const Icon(Icons.image, color: AppColors.mist),
            ),
          ),
        ),
        if (isPrimary)
          Positioned(
            bottom: 4,
            start: 4,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: AppColors.gold,
                borderRadius: AppSpacing.radiusSm,
              ),
              child: const Text('رئيسية',
                  style: TextStyle(
                      fontSize: 9,
                      color: Colors.white,
                      fontWeight: FontWeight.w600)),
            ),
          ),
        Positioned(
          top: 4,
          end: 4,
          child: GestureDetector(
            onTap: onRemove,
            child: Container(
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                color: Colors.black.withOpacity(0.5),
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.close, size: 14, color: Colors.white),
            ),
          ),
        ),
      ],
    );
  }
}

// ── Step 2: Details ───────────────────────────────────────────

class _DetailsStep extends ConsumerWidget {
  const _DetailsStep({required this.formKey});
  final GlobalKey<FormState> formKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(createListingProvider);
    final notifier = ref.read(createListingProvider.notifier);

    return Form(
      key: formKey,
      child: ListView(
        padding: AppSpacing.allMd,
        children: [
          // AI Suggestion banner
          if (s.snapResult != null)
            Container(
              padding: AppSpacing.allSm,
              margin: const EdgeInsetsDirectional.only(bottom: 16),
              decoration: BoxDecoration(
                color: AppColors.emerald.withOpacity(0.08),
                borderRadius: AppSpacing.radiusMd,
                border: Border.all(color: AppColors.emerald.withOpacity(0.2)),
              ),
              child: const Row(
                children: [
                  Icon(Icons.auto_awesome, size: 16, color: AppColors.emerald),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'تم ملء الحقول تلقائياً بالذكاء الاصطناعي — يمكنك التعديل',
                      style: TextStyle(fontSize: 12, color: AppColors.emerald),
                    ),
                  ),
                ],
              ),
            ),

          // Title (Arabic)
          _buildLabel('العنوان بالعربية *'),
          TextFormField(
            initialValue: s.titleAr,
            textDirection: TextDirection.rtl,
            decoration: _inputDecor('مثال: ساعة رولكس أصلية ٢٠٢٤'),
            maxLength: 200,
            validator: (v) {
              if (v == null || v.length < 3) return 'الحد الأدنى ٣ أحرف';
              if (!RegExp(r'[\u0600-\u06FF]').hasMatch(v)) {
                return 'يجب أن يحتوي على حرف عربي واحد على الأقل';
              }
              return null;
            },
            onChanged: notifier.updateTitleAr,
          ),

          const SizedBox(height: AppSpacing.md),

          // Title (English)
          _buildLabel('Title in English *'),
          TextFormField(
            initialValue: s.titleEn,
            decoration: _inputDecor('e.g. Original Rolex Watch 2024'),
            maxLength: 200,
            validator: (v) =>
                (v == null || v.length < 3) ? 'Minimum 3 characters' : null,
            onChanged: notifier.updateTitleEn,
          ),

          const SizedBox(height: AppSpacing.md),

          // Description (Arabic)
          _buildLabel('الوصف بالعربية'),
          TextFormField(
            initialValue: s.descriptionAr,
            textDirection: TextDirection.rtl,
            decoration: _inputDecor('وصف تفصيلي للمنتج...'),
            maxLines: 4,
            maxLength: 5000,
            onChanged: notifier.updateDescriptionAr,
          ),

          const SizedBox(height: AppSpacing.md),

          // Description (English)
          _buildLabel('Description in English'),
          TextFormField(
            initialValue: s.descriptionEn,
            decoration: _inputDecor('Detailed description...'),
            maxLines: 4,
            maxLength: 5000,
            onChanged: notifier.updateDescriptionEn,
          ),

          const SizedBox(height: AppSpacing.lg),

          // Category picker
          _buildLabel('التصنيف *'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: kCategories.map((cat) {
              final selected = s.categoryId == cat.id;
              return ChoiceChip(
                label: Text('${cat.icon} ${cat.nameAr}'),
                selected: selected,
                onSelected: (_) => notifier.updateCategoryId(cat.id),
                selectedColor: AppColors.gold.withOpacity(0.2),
                backgroundColor: AppColors.sand.withOpacity(0.5),
                labelStyle: TextStyle(
                  fontSize: 13,
                  color: selected ? AppColors.gold : AppColors.ink,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                ),
                side: BorderSide(
                  color: selected
                      ? AppColors.gold
                      : AppColors.mist.withOpacity(0.2),
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusSm,
                ),
              );
            }).toList(),
          ),

          const SizedBox(height: AppSpacing.lg),

          // Condition picker
          _buildLabel('حالة المنتج *'),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: kConditions.map((cond) {
              final selected = s.condition == cond.value;
              return ChoiceChip(
                label: Text(cond.labelAr),
                selected: selected,
                onSelected: (_) => notifier.updateCondition(cond.value),
                selectedColor: AppColors.navy.withOpacity(0.15),
                backgroundColor: AppColors.sand.withOpacity(0.5),
                labelStyle: TextStyle(
                  fontSize: 13,
                  color: selected ? AppColors.navy : AppColors.ink,
                  fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                ),
                side: BorderSide(
                  color: selected
                      ? AppColors.navy
                      : AppColors.mist.withOpacity(0.2),
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusSm,
                ),
              );
            }).toList(),
          ),

          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }
}

// ── Step 3: Pricing ───────────────────────────────────────────

class _PricingStep extends ConsumerWidget {
  const _PricingStep({required this.formKey});
  final GlobalKey<FormState> formKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(createListingProvider);
    final notifier = ref.read(createListingProvider.notifier);

    return Form(
      key: formKey,
      child: ListView(
        padding: AppSpacing.allMd,
        children: [
          // AI price suggestion
          if (s.snapResult?.suggestedStart != null)
            Container(
              padding: AppSpacing.allMd,
              margin: const EdgeInsetsDirectional.only(bottom: 16),
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [
                    AppColors.gold.withOpacity(0.08),
                    AppColors.gold.withOpacity(0.03),
                  ],
                ),
                borderRadius: AppSpacing.radiusMd,
                border: Border.all(color: AppColors.gold.withOpacity(0.2)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Row(
                    children: [
                      Icon(Icons.auto_awesome, size: 16, color: AppColors.gold),
                      SizedBox(width: 8),
                      Text('تقدير السعر بالذكاء الاصطناعي',
                          style: TextStyle(
                              fontSize: 13,
                              fontWeight: FontWeight.w600,
                              color: AppColors.gold)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '${_formatPrice(s.snapResult!.priceLow)} — ${_formatPrice(s.snapResult!.priceHigh)} د.أ',
                    style: const TextStyle(
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                      fontFamily: 'Sora',
                    ),
                  ),
                  Text(
                    'السعر المقترح: ${_formatPrice(s.snapResult!.suggestedStart)} د.أ',
                    style: const TextStyle(
                        fontSize: 12, color: AppColors.mist),
                  ),
                ],
              ),
            ),

          // Starting price
          _buildLabel('سعر البداية (د.أ) *'),
          TextFormField(
            initialValue: s.startingPrice != null
                ? (s.startingPrice! / 100).toStringAsFixed(0)
                : '',
            keyboardType: TextInputType.number,
            decoration: _inputDecor('الحد الأدنى ١ د.أ'),
            validator: (v) {
              if (v == null || v.isEmpty) return 'مطلوب';
              final n = int.tryParse(v);
              if (n == null || n < 1) return 'الحد الأدنى ١ د.أ';
              return null;
            },
            onChanged: (v) {
              final n = int.tryParse(v);
              notifier.updateStartingPrice(n != null ? n * 100 : null);
            },
          ),

          const SizedBox(height: AppSpacing.md),

          // Reserve price (optional)
          _buildLabel('السعر الاحتياطي (اختياري)'),
          TextFormField(
            initialValue: s.reservePrice != null
                ? (s.reservePrice! / 100).toStringAsFixed(0)
                : '',
            keyboardType: TextInputType.number,
            decoration:
                _inputDecor('لن يُباع بأقل من هذا السعر'),
            onChanged: (v) {
              final n = int.tryParse(v);
              notifier.updateReservePrice(n != null ? n * 100 : null);
            },
          ),

          const SizedBox(height: AppSpacing.md),

          // Buy it now (optional)
          _buildLabel('سعر الشراء الفوري (اختياري)'),
          TextFormField(
            initialValue: s.buyNowPrice != null
                ? (s.buyNowPrice! / 100).toStringAsFixed(0)
                : '',
            keyboardType: TextInputType.number,
            decoration: _inputDecor('يُباع فوراً بهذا السعر'),
            onChanged: (v) {
              final n = int.tryParse(v);
              notifier.updateBuyNowPrice(n != null ? n * 100 : null);
            },
          ),

          const SizedBox(height: AppSpacing.md),

          // Min increment
          _buildLabel('الحد الأدنى للمزايدة (د.أ)'),
          TextFormField(
            initialValue: (s.minIncrement / 100).toStringAsFixed(0),
            keyboardType: TextInputType.number,
            decoration: _inputDecor('الافتراضي ٢٥ د.أ'),
            onChanged: (v) {
              final n = int.tryParse(v);
              if (n != null && n >= 1) notifier.updateMinIncrement(n * 100);
            },
          ),

          const SizedBox(height: AppSpacing.xl),
        ],
      ),
    );
  }

  static String _formatPrice(int? cents) {
    if (cents == null) return '—';
    return (cents / 100).toStringAsFixed(0);
  }
}

// ── Step 4: Schedule ──────────────────────────────────────────

class _ScheduleStep extends ConsumerWidget {
  const _ScheduleStep();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(createListingProvider);
    final notifier = ref.read(createListingProvider.notifier);

    return ListView(
      padding: AppSpacing.allMd,
      children: [
        // Start time
        _buildLabel('وقت البدء'),
        SwitchListTile(
          title: const Text('ابدأ فوراً',
              style: TextStyle(fontSize: 14, color: AppColors.navy)),
          value: s.startNow,
          onChanged: notifier.updateStartNow,
          activeColor: AppColors.gold,
          contentPadding: EdgeInsets.zero,
        ),

        if (!s.startNow) ...[
          const SizedBox(height: 8),
          GestureDetector(
            onTap: () async {
              final date = await showDatePicker(
                context: context,
                initialDate:
                    DateTime.now().add(const Duration(minutes: 30)),
                firstDate: DateTime.now(),
                lastDate:
                    DateTime.now().add(const Duration(days: 30)),
              );
              if (date == null) return;
              if (!context.mounted) return;
              final time = await showTimePicker(
                context: context,
                initialTime: TimeOfDay.now(),
              );
              if (time == null) return;
              final dt = DateTime(
                date.year, date.month, date.day,
                time.hour, time.minute,
              ).toUtc();
              notifier.updateStartsAt(dt);
            },
            child: Container(
              padding: AppSpacing.allMd,
              decoration: BoxDecoration(
                color: Colors.white,
                borderRadius: AppSpacing.radiusMd,
                border: Border.all(color: AppColors.sand),
              ),
              child: Row(
                children: [
                  const Icon(Icons.calendar_today_rounded,
                      size: 18, color: AppColors.mist),
                  const SizedBox(width: 12),
                  Text(
                    s.startsAt != null
                        ? '${s.startsAt!.day}/${s.startsAt!.month}/${s.startsAt!.year} ${s.startsAt!.hour}:${s.startsAt!.minute.toString().padLeft(2, '0')}'
                        : 'اختر تاريخ ووقت البدء',
                    style: TextStyle(
                      fontSize: 14,
                      color: s.startsAt != null
                          ? AppColors.ink
                          : AppColors.mist,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],

        const SizedBox(height: AppSpacing.lg),

        // Duration
        _buildLabel('مدة المزاد'),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: List.generate(kDurations.length, (i) {
            final d = kDurations[i];
            final selected = s.durationIndex == i;
            return ChoiceChip(
              label: Text(d.labelAr),
              selected: selected,
              onSelected: (_) => notifier.updateDurationIndex(i),
              selectedColor: AppColors.navy.withOpacity(0.15),
              backgroundColor: AppColors.sand.withOpacity(0.5),
              labelStyle: TextStyle(
                fontSize: 13,
                fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                color: selected ? AppColors.navy : AppColors.ink,
              ),
              side: BorderSide(
                color: selected
                    ? AppColors.navy
                    : AppColors.mist.withOpacity(0.2),
              ),
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.radiusSm,
              ),
            );
          }),
        ),

        const SizedBox(height: AppSpacing.lg),

        // Location
        _buildLabel('المدينة'),
        TextFormField(
          initialValue: s.locationCity,
          decoration: _inputDecor('مثال: عمّان'),
          onChanged: notifier.updateLocationCity,
        ),

        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

// ── Step 5: Review & Publish ──────────────────────────────────

class _ReviewStep extends ConsumerWidget {
  const _ReviewStep({required this.onEditSection});
  final void Function(int step) onEditSection;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(createListingProvider);

    final category =
        kCategories.where((c) => c.id == s.categoryId).firstOrNull;
    final condition =
        kConditions.where((c) => c.value == s.condition).firstOrNull;

    return ListView(
      padding: AppSpacing.allMd,
      children: [
        const Text(
          'مراجعة القائمة',
          style: TextStyle(
            fontSize: 20,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: AppSpacing.lg),

        // Photos summary
        _ReviewSection(
          title: 'الصور',
          step: 0,
          onEdit: onEditSection,
          child: SizedBox(
            height: 80,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: s.photos.length,
              separatorBuilder: (_, __) => const SizedBox(width: 8),
              itemBuilder: (_, i) => ClipRRect(
                borderRadius: AppSpacing.radiusSm,
                child: Image.network(
                  s.photos[i].path,
                  width: 80,
                  height: 80,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => Container(
                    width: 80,
                    height: 80,
                    color: AppColors.sand,
                    child: const Icon(Icons.image, color: AppColors.mist),
                  ),
                ),
              ),
            ),
          ),
        ),

        // Details summary
        _ReviewSection(
          title: 'التفاصيل',
          step: 1,
          onEdit: onEditSection,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _reviewRow('العنوان', s.titleAr),
              _reviewRow('Title', s.titleEn),
              _reviewRow('التصنيف', category?.nameAr ?? '—'),
              _reviewRow('الحالة', condition?.labelAr ?? '—'),
              if (s.descriptionAr != null && s.descriptionAr!.isNotEmpty)
                _reviewRow('الوصف', s.descriptionAr!.length > 60
                    ? '${s.descriptionAr!.substring(0, 60)}...'
                    : s.descriptionAr!),
            ],
          ),
        ),

        // Pricing summary
        _ReviewSection(
          title: 'الأسعار',
          step: 2,
          onEdit: onEditSection,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _reviewRow('سعر البداية',
                  '${(s.startingPrice ?? 0) ~/ 100} د.أ'),
              if (s.reservePrice != null)
                _reviewRow('السعر الاحتياطي',
                    '${s.reservePrice! ~/ 100} د.أ'),
              if (s.buyNowPrice != null)
                _reviewRow('الشراء الفوري',
                    '${s.buyNowPrice! ~/ 100} د.أ'),
              _reviewRow('أقل مزايدة',
                  '${s.minIncrement ~/ 100} د.أ'),
            ],
          ),
        ),

        // Schedule summary
        _ReviewSection(
          title: 'الجدولة',
          step: 3,
          onEdit: onEditSection,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _reviewRow('البدء', s.startNow ? 'فوراً' : '${s.startsAt ?? "—"}'),
              _reviewRow('المدة', kDurations[s.durationIndex].labelAr),
              if (s.locationCity != null)
                _reviewRow('المدينة', s.locationCity!),
            ],
          ),
        ),

        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }

  static Widget _reviewRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 100,
            child: Text(label,
                style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.mist,
                    fontWeight: FontWeight.w500)),
          ),
          Expanded(
            child: Text(value,
                style: const TextStyle(
                    fontSize: 13,
                    color: AppColors.ink,
                    fontWeight: FontWeight.w500)),
          ),
        ],
      ),
    );
  }
}

class _ReviewSection extends StatelessWidget {
  const _ReviewSection({
    required this.title,
    required this.step,
    required this.onEdit,
    required this.child,
  });
  final String title;
  final int step;
  final void Function(int) onEdit;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: AppSpacing.radiusMd,
        border: Border.all(color: AppColors.sand),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(title,
                  style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy)),
              GestureDetector(
                onTap: () => onEdit(step),
                child: const Text('تعديل',
                    style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: AppColors.gold)),
              ),
            ],
          ),
          const SizedBox(height: 8),
          child,
        ],
      ),
    );
  }
}

// ── Buttons ───────────────────────────────────────────────────

class _NextButton extends StatelessWidget {
  const _NextButton({required this.onPressed});
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: AppColors.gold,
      borderRadius: AppSpacing.radiusMd,
      child: InkWell(
        onTap: onPressed,
        borderRadius: AppSpacing.radiusMd,
        child: const SizedBox(
          height: 50,
          child: Center(
            child: Text(
              'التالي',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PublishButton extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(createListingProvider);
    final isLoading = s.isPublishing || s.isUploading || s.isCreating;

    return Material(
      color: isLoading ? AppColors.gold.withOpacity(0.6) : AppColors.gold,
      borderRadius: AppSpacing.radiusMd,
      child: InkWell(
        onTap: isLoading ? null : () => _handlePublish(context, ref),
        borderRadius: AppSpacing.radiusMd,
        child: SizedBox(
          height: 50,
          child: Center(
            child: isLoading
                ? const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(
                      strokeWidth: 2.5,
                      valueColor: AlwaysStoppedAnimation(Colors.white),
                    ),
                  )
                : const Text(
                    'نشر المنتج',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                      color: Colors.white,
                    ),
                  ),
          ),
        ),
      ),
    );
  }

  Future<void> _handlePublish(BuildContext context, WidgetRef ref) async {
    HapticFeedback.mediumImpact();
    final notifier = ref.read(createListingProvider.notifier);

    // Upload photos if not done yet
    final s = ref.read(createListingProvider);
    if (s.uploadedS3Keys.isEmpty) {
      final uploaded = await notifier.createDraftAndUpload();
      if (!uploaded) return;
    }

    // Publish
    final success = await notifier.publish();
    if (success) {
      AppHaptics.bidConfirmed();
    }
  }
}

// ── Success Screen ────────────────────────────────────────────

class _SuccessScreen extends StatelessWidget {
  const _SuccessScreen({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final isPending = status == 'pending_review';

    return Scaffold(
      backgroundColor: AppColors.cream,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: AppSpacing.allXl,
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  isPending
                      ? Icons.hourglass_top_rounded
                      : Icons.check_circle_rounded,
                  size: 72,
                  color: isPending ? AppColors.gold : AppColors.emerald,
                ),
                const SizedBox(height: AppSpacing.lg),
                Text(
                  isPending ? 'بانتظار المراجعة' : 'تم النشر بنجاح!',
                  style: const TextStyle(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  isPending
                      ? 'سيتم مراجعة منتجك خلال ساعتين وإشعارك بالنتيجة'
                      : 'منتجك متاح الآن للمزايدة',
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 14, color: AppColors.mist),
                ),
                const SizedBox(height: AppSpacing.xxl),
                SizedBox(
                  width: double.infinity,
                  height: 50,
                  child: Material(
                    color: AppColors.navy,
                    borderRadius: AppSpacing.radiusMd,
                    child: InkWell(
                      onTap: () => context.pop(),
                      borderRadius: AppSpacing.radiusMd,
                      child: const Center(
                        child: Text(
                          'تم',
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
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ── Shared helpers ────────────────────────────────────────────

Widget _buildLabel(String text) => Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w600,
          color: AppColors.navy,
        ),
      ),
    );

InputDecoration _inputDecor(String hint) => InputDecoration(
      hintText: hint,
      hintStyle: TextStyle(color: AppColors.mist.withOpacity(0.6), fontSize: 14),
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      border: OutlineInputBorder(
        borderRadius: AppSpacing.radiusMd,
        borderSide: const BorderSide(color: AppColors.sand),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: AppSpacing.radiusMd,
        borderSide: const BorderSide(color: AppColors.sand),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: AppSpacing.radiusMd,
        borderSide: const BorderSide(color: AppColors.navy, width: 1.5),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: AppSpacing.radiusMd,
        borderSide: const BorderSide(color: AppColors.ember),
      ),
    );
