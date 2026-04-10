import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import 'core_providers.dart';

// ── Categories (SDD §4.2) ─────────────────────────────────────

class ListingCategory {
  const ListingCategory(this.id, this.nameAr, this.nameEn, this.icon);
  final int id;
  final String nameAr;
  final String nameEn;
  final String icon;
}

const kCategories = [
  ListingCategory(1, 'إلكترونيات', 'Electronics', '📱'),
  ListingCategory(2, 'مركبات', 'Vehicles', '🚗'),
  ListingCategory(3, 'عقارات', 'Real Estate', '🏠'),
  ListingCategory(4, 'أزياء', 'Fashion', '👗'),
  ListingCategory(5, 'أثاث ومنزل', 'Home & Furniture', '🛋'),
  ListingCategory(6, 'رياضة', 'Sports', '⚽'),
  ListingCategory(7, 'مقتنيات', 'Collectibles', '🏺'),
  ListingCategory(8, 'مجوهرات', 'Jewelry', '💍'),
  ListingCategory(9, 'كتب ومطبوعات', 'Books', '📚'),
  ListingCategory(10, 'ألعاب', 'Games & Toys', '🎮'),
  ListingCategory(11, 'صحة وجمال', 'Health & Beauty', '💄'),
  ListingCategory(99, 'أخرى', 'Other', '📦'),
];

// ── Conditions ────────────────────────────────────────────────

class ItemCondition {
  const ItemCondition(this.value, this.labelAr, this.labelEn);
  final String value;
  final String labelAr;
  final String labelEn;
}

const kConditions = [
  ItemCondition('brand_new', 'جديد', 'Brand New'),
  ItemCondition('like_new', 'شبه جديد', 'Like New'),
  ItemCondition('very_good', 'ممتاز', 'Very Good'),
  ItemCondition('good', 'جيد', 'Good'),
  ItemCondition('acceptable', 'مقبول', 'Acceptable'),
];

// ── Duration presets ──────────────────────────────────────────

class DurationPreset {
  const DurationPreset(this.duration, this.labelAr, this.labelEn);
  final Duration duration;
  final String labelAr;
  final String labelEn;
}

const kDurations = [
  DurationPreset(Duration(hours: 1), '١ ساعة', '1h'),
  DurationPreset(Duration(hours: 3), '٣ ساعات', '3h'),
  DurationPreset(Duration(hours: 6), '٦ ساعات', '6h'),
  DurationPreset(Duration(hours: 12), '١٢ ساعة', '12h'),
  DurationPreset(Duration(hours: 24), 'يوم', '24h'),
  DurationPreset(Duration(days: 3), '٣ أيام', '3d'),
  DurationPreset(Duration(days: 7), '٧ أيام', '7d'),
];

// ── Snap-to-List result model ─────────────────────────────────

class SnapResult {
  const SnapResult({
    this.titleAr = '',
    this.titleEn = '',
    this.descriptionAr,
    this.descriptionEn,
    this.categoryId,
    this.condition,
    this.priceLow,
    this.priceHigh,
    this.suggestedStart,
    this.confidence,
    this.partial = false,
  });

  final String titleAr;
  final String titleEn;
  final String? descriptionAr;
  final String? descriptionEn;
  final int? categoryId;
  final String? condition;
  final int? priceLow;
  final int? priceHigh;
  final int? suggestedStart;
  final String? confidence;
  final bool partial;

  factory SnapResult.fromJson(Map<String, dynamic> json) => SnapResult(
        titleAr: json['title_ar'] as String? ?? '',
        titleEn: json['title_en'] as String? ?? '',
        descriptionAr: json['description_ar'] as String?,
        descriptionEn: json['description_en'] as String?,
        categoryId: json['category_id'] as int?,
        condition: json['condition'] as String?,
        priceLow: json['price_estimate']?['price_low'] as int?,
        priceHigh: json['price_estimate']?['price_high'] as int?,
        suggestedStart: json['price_estimate']?['suggested_start'] as int?,
        confidence: json['price_estimate']?['confidence'] as String?,
        partial: json['partial'] as bool? ?? false,
      );
}

// ── State ─────────────────────────────────────────────────────

class CreateListingState {
  const CreateListingState({
    this.currentStep = 0,
    this.photos = const [],
    this.uploadedS3Keys = const [],
    this.uploadProgress = 0.0,
    this.titleAr = '',
    this.titleEn = '',
    this.descriptionAr,
    this.descriptionEn,
    this.categoryId,
    this.condition = 'good',
    this.startingPrice,
    this.reservePrice,
    this.buyNowPrice,
    this.minIncrement = 2500,
    this.startNow = true,
    this.startsAt,
    this.durationIndex = 2,
    this.locationCity,
    this.locationCountry = 'JO',
    this.isCharity = false,
    this.isCertified = false,
    this.ngoId,
    this.isCreating = false,
    this.isUploading = false,
    this.isPublishing = false,
    this.isRunningAI = false,
    this.error,
    this.draftListingId,
    this.snapResult,
    this.publishedStatus,
  });

  final int currentStep;
  final List<XFile> photos;
  final List<String> uploadedS3Keys;
  final double uploadProgress;
  final String titleAr;
  final String titleEn;
  final String? descriptionAr;
  final String? descriptionEn;
  final int? categoryId;
  final String condition;
  final int? startingPrice; // cents
  final int? reservePrice;
  final int? buyNowPrice;
  final int minIncrement;
  final bool startNow;
  final DateTime? startsAt;
  final int durationIndex; // index into kDurations
  final String? locationCity;
  final String locationCountry;
  final bool isCharity;
  final bool isCertified;
  final int? ngoId;
  final bool isCreating;
  final bool isUploading;
  final bool isPublishing;
  final bool isRunningAI;
  final String? error;
  final String? draftListingId;
  final SnapResult? snapResult;
  final String? publishedStatus; // 'active' or 'pending_review'

  bool get canProceedFromPhotos => photos.length >= 3;
  bool get canProceedFromDetails =>
      titleAr.length >= 3 &&
      titleEn.length >= 3 &&
      categoryId != null &&
      _containsArabic(titleAr);
  bool get canProceedFromPricing =>
      startingPrice != null && startingPrice! >= 100;
  bool get canProceedFromSchedule => true;
  bool get canPublish =>
      canProceedFromPhotos &&
      canProceedFromDetails &&
      canProceedFromPricing &&
      !isPublishing;

  Duration get selectedDuration => kDurations[durationIndex].duration;

  DateTime get computedStartsAt {
    if (startNow) {
      return DateTime.now().toUtc().add(const Duration(minutes: 6));
    }
    return startsAt ?? DateTime.now().toUtc().add(const Duration(minutes: 30));
  }

  DateTime get computedEndsAt => computedStartsAt.add(selectedDuration);

  static bool _containsArabic(String text) {
    return RegExp(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')
        .hasMatch(text);
  }

  CreateListingState copyWith({
    int? currentStep,
    List<XFile>? photos,
    List<String>? uploadedS3Keys,
    double? uploadProgress,
    String? titleAr,
    String? titleEn,
    String? descriptionAr,
    String? descriptionEn,
    int? categoryId,
    String? condition,
    int? startingPrice,
    int? reservePrice,
    int? buyNowPrice,
    int? minIncrement,
    bool? startNow,
    DateTime? startsAt,
    int? durationIndex,
    String? locationCity,
    String? locationCountry,
    bool? isCharity,
    bool? isCertified,
    int? ngoId,
    bool? isCreating,
    bool? isUploading,
    bool? isPublishing,
    bool? isRunningAI,
    String? error,
    String? draftListingId,
    SnapResult? snapResult,
    String? publishedStatus,
    bool clearError = false,
    bool clearReserve = false,
    bool clearBuyNow = false,
  }) =>
      CreateListingState(
        currentStep: currentStep ?? this.currentStep,
        photos: photos ?? this.photos,
        uploadedS3Keys: uploadedS3Keys ?? this.uploadedS3Keys,
        uploadProgress: uploadProgress ?? this.uploadProgress,
        titleAr: titleAr ?? this.titleAr,
        titleEn: titleEn ?? this.titleEn,
        descriptionAr: descriptionAr ?? this.descriptionAr,
        descriptionEn: descriptionEn ?? this.descriptionEn,
        categoryId: categoryId ?? this.categoryId,
        condition: condition ?? this.condition,
        startingPrice: startingPrice ?? this.startingPrice,
        reservePrice: clearReserve ? null : (reservePrice ?? this.reservePrice),
        buyNowPrice: clearBuyNow ? null : (buyNowPrice ?? this.buyNowPrice),
        minIncrement: minIncrement ?? this.minIncrement,
        startNow: startNow ?? this.startNow,
        startsAt: startsAt ?? this.startsAt,
        durationIndex: durationIndex ?? this.durationIndex,
        locationCity: locationCity ?? this.locationCity,
        locationCountry: locationCountry ?? this.locationCountry,
        isCharity: isCharity ?? this.isCharity,
        isCertified: isCertified ?? this.isCertified,
        ngoId: ngoId ?? this.ngoId,
        isCreating: isCreating ?? this.isCreating,
        isUploading: isUploading ?? this.isUploading,
        isPublishing: isPublishing ?? this.isPublishing,
        isRunningAI: isRunningAI ?? this.isRunningAI,
        error: clearError ? null : (error ?? this.error),
        draftListingId: draftListingId ?? this.draftListingId,
        snapResult: snapResult ?? this.snapResult,
        publishedStatus: publishedStatus ?? this.publishedStatus,
      );
}

// ── Provider ──────────────────────────────────────────────────

final createListingProvider =
    StateNotifierProvider.autoDispose<CreateListingNotifier, CreateListingState>(
  (ref) => CreateListingNotifier(ref),
);

class CreateListingNotifier extends StateNotifier<CreateListingState> {
  CreateListingNotifier(this._ref) : super(const CreateListingState());

  final Ref _ref;

  // ── Photo management ────────────────────────────────────────

  void addPhotos(List<XFile> newPhotos) {
    final combined = [...state.photos, ...newPhotos];
    if (combined.length > 20) {
      state = state.copyWith(
        photos: combined.sublist(0, 20),
        error: 'الحد الأقصى ٢٠ صورة', // Max 20 images
        clearError: false,
      );
      return;
    }
    state = state.copyWith(photos: combined, clearError: true);
  }

  void removePhoto(int index) {
    final updated = [...state.photos]..removeAt(index);
    state = state.copyWith(photos: updated, clearError: true);
  }

  void reorderPhotos(int oldIndex, int newIndex) {
    final photos = [...state.photos];
    if (newIndex > oldIndex) newIndex--;
    final item = photos.removeAt(oldIndex);
    photos.insert(newIndex, item);
    state = state.copyWith(photos: photos);
  }

  // ── Details ─────────────────────────────────────────────────

  void updateTitleAr(String v) => state = state.copyWith(titleAr: v);
  void updateTitleEn(String v) => state = state.copyWith(titleEn: v);
  void updateDescriptionAr(String? v) =>
      state = state.copyWith(descriptionAr: v);
  void updateDescriptionEn(String? v) =>
      state = state.copyWith(descriptionEn: v);
  void updateCategoryId(int v) => state = state.copyWith(categoryId: v);
  void updateCondition(String v) => state = state.copyWith(condition: v);

  // ── Pricing ─────────────────────────────────────────────────

  void updateStartingPrice(int? v) =>
      state = state.copyWith(startingPrice: v);
  void updateReservePrice(int? v) =>
      state = state.copyWith(reservePrice: v, clearReserve: v == null);
  void updateBuyNowPrice(int? v) =>
      state = state.copyWith(buyNowPrice: v, clearBuyNow: v == null);
  void updateMinIncrement(int v) => state = state.copyWith(minIncrement: v);

  // ── Schedule ────────────────────────────────────────────────

  void updateStartNow(bool v) => state = state.copyWith(startNow: v);
  void updateStartsAt(DateTime v) => state = state.copyWith(startsAt: v);
  void updateDurationIndex(int v) => state = state.copyWith(durationIndex: v);
  void updateLocationCity(String? v) =>
      state = state.copyWith(locationCity: v);
  void updateIsCharity(bool v) => state = state.copyWith(isCharity: v);
  void updateIsCertified(bool v) => state = state.copyWith(isCertified: v);

  // ── Navigation ──────────────────────────────────────────────

  void nextStep() {
    if (state.currentStep < 4) {
      state = state.copyWith(
        currentStep: state.currentStep + 1,
        clearError: true,
      );
    }
  }

  void previousStep() {
    if (state.currentStep > 0) {
      state = state.copyWith(
        currentStep: state.currentStep - 1,
        clearError: true,
      );
    }
  }

  void goToStep(int step) {
    state = state.copyWith(currentStep: step.clamp(0, 4), clearError: true);
  }

  // ── Apply Snap-to-List result ───────────────────────────────

  void applySnapResult(SnapResult result) {
    state = state.copyWith(
      snapResult: result,
      titleAr: result.titleAr.isNotEmpty ? result.titleAr : state.titleAr,
      titleEn: result.titleEn.isNotEmpty ? result.titleEn : state.titleEn,
      descriptionAr: result.descriptionAr ?? state.descriptionAr,
      descriptionEn: result.descriptionEn ?? state.descriptionEn,
      categoryId: result.categoryId ?? state.categoryId,
      condition: result.condition ?? state.condition,
      startingPrice: result.suggestedStart ?? state.startingPrice,
    );
  }

  // ── Create draft + upload images ────────────────────────────

  Future<bool> createDraftAndUpload() async {
    if (state.photos.isEmpty) return false;
    final api = _ref.read(apiClientProvider);

    state = state.copyWith(isUploading: true, clearError: true);

    try {
      // Step 1: Create draft listing
      if (state.draftListingId == null) {
        state = state.copyWith(isCreating: true);
        final createResp = await api.post('/listings/', data: {
          'title_ar': state.titleAr.isNotEmpty ? state.titleAr : 'مسودة',
          'title_en': state.titleEn.isNotEmpty ? state.titleEn : 'Draft',
          'category_id': state.categoryId ?? 99,
          'condition': state.condition,
          'starting_price': state.startingPrice ?? 100,
          'min_increment': state.minIncrement,
          'starts_at': state.computedStartsAt.toIso8601String(),
          'ends_at': state.computedEndsAt.toIso8601String(),
          'location_country': state.locationCountry,
          if (state.descriptionAr != null) 'description_ar': state.descriptionAr,
          if (state.descriptionEn != null) 'description_en': state.descriptionEn,
          if (state.locationCity != null) 'location_city': state.locationCity,
          if (state.reservePrice != null) 'reserve_price': state.reservePrice,
          if (state.buyNowPrice != null) 'buy_it_now_price': state.buyNowPrice,
          'is_charity': state.isCharity,
          'is_certified': state.isCertified,
          if (state.ngoId != null) 'ngo_id': state.ngoId,
        });
        final listingId = createResp.data['id'] as String;
        state = state.copyWith(draftListingId: listingId, isCreating: false);
      }

      final listingId = state.draftListingId!;

      // Step 2: Request presigned upload URLs
      final urlResp = await api.post(
        '/listings/$listingId/images/request',
        data: {'count': state.photos.length},
      );
      final uploadUrls = (urlResp.data['upload_urls'] as List)
          .cast<Map<String, dynamic>>();

      // Step 3: Upload each image to S3
      final s3Keys = <String>[];
      final uploadDio = Dio(); // Raw Dio for S3 (no auth header)
      for (var i = 0; i < state.photos.length; i++) {
        final photo = state.photos[i];
        final presignedUrl = uploadUrls[i]['upload_url'] as String;
        final s3Key = uploadUrls[i]['s3_key'] as String;

        final bytes = await File(photo.path).readAsBytes();
        await uploadDio.put(
          presignedUrl,
          data: bytes,
          options: Options(headers: {
            'Content-Type': 'image/jpeg',
            'Content-Length': bytes.length,
          }),
        );

        s3Keys.add(s3Key);
        state = state.copyWith(
          uploadProgress: (i + 1) / state.photos.length,
        );
      }

      // Step 4: Confirm uploads
      await api.post(
        '/listings/$listingId/images/confirm',
        data: {'s3_keys': s3Keys},
      );

      state = state.copyWith(
        uploadedS3Keys: s3Keys,
        isUploading: false,
        uploadProgress: 1.0,
      );
      return true;
    } catch (e) {
      state = state.copyWith(
        isUploading: false,
        isCreating: false,
        error: e is DioException
            ? (e.response?.data?['detail']?.toString() ?? e.message)
            : e.toString(),
      );
      return false;
    }
  }

  // ── Run Snap-to-List AI pipeline ────────────────────────────

  Future<SnapResult?> runSnapToList() async {
    if (state.uploadedS3Keys.isEmpty) return null;
    final api = _ref.read(apiClientProvider);

    state = state.copyWith(isRunningAI: true, clearError: true);

    try {
      final resp = await api.post(
        '/ai/snap-to-list',
        data: {'image_s3_keys': state.uploadedS3Keys},
        options: Options(receiveTimeout: const Duration(seconds: 30)),
      );

      final result = SnapResult.fromJson(resp.data as Map<String, dynamic>);
      applySnapResult(result);
      state = state.copyWith(isRunningAI: false);
      return result;
    } catch (e) {
      state = state.copyWith(
        isRunningAI: false,
        error: 'فشل تحليل الذكاء الاصطناعي — يمكنك الإدخال يدوياً',
      );
      return null;
    }
  }

  // ── Publish listing ─────────────────────────────────────────

  Future<bool> publish() async {
    final api = _ref.read(apiClientProvider);
    final listingId = state.draftListingId;

    if (listingId == null) {
      state = state.copyWith(error: 'لم يتم إنشاء المسودة بعد');
      return false;
    }

    state = state.copyWith(isPublishing: true, clearError: true);

    try {
      // Update draft with final values before publishing
      await api.put('/listings/$listingId', data: {
        'title_ar': state.titleAr,
        'title_en': state.titleEn,
        if (state.descriptionAr != null) 'description_ar': state.descriptionAr,
        if (state.descriptionEn != null) 'description_en': state.descriptionEn,
        'category_id': state.categoryId,
        'condition': state.condition,
        'starting_price': state.startingPrice,
        'min_increment': state.minIncrement,
        'starts_at': state.computedStartsAt.toIso8601String(),
        'ends_at': state.computedEndsAt.toIso8601String(),
        'location_country': state.locationCountry,
        if (state.locationCity != null) 'location_city': state.locationCity,
        if (state.reservePrice != null) 'reserve_price': state.reservePrice,
        if (state.buyNowPrice != null) 'buy_it_now_price': state.buyNowPrice,
        'is_charity': state.isCharity,
        'is_certified': state.isCertified,
      });

      // Publish
      final resp = await api.post('/listings/$listingId/publish');
      final status = resp.data['status'] as String;
      state = state.copyWith(
        isPublishing: false,
        publishedStatus: status,
      );
      return true;
    } catch (e) {
      state = state.copyWith(
        isPublishing: false,
        error: e is DioException
            ? (e.response?.data?['detail']?.toString() ?? e.message)
            : e.toString(),
      );
      return false;
    }
  }

  // ── Reset ───────────────────────────────────────────────────

  void reset() => state = const CreateListingState();
}
