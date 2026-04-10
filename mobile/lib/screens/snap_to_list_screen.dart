import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../core/l10n/arabic_numerals.dart';
import '../core/providers/core_providers.dart';
import '../core/theme/animations.dart';
import '../core/theme/colors.dart';
import '../core/theme/haptics.dart';
import '../core/theme/spacing.dart';

// ═══════════════════════════════════════════════════════════════════════
//  Snap-to-List Screen — AI pipeline progress UI
// ═══════════════════════════════════════════════════════════════════════
//
//  Photo capture → S3 upload → POST /api/v1/ai/snap-to-list
//  5-step pipeline: CLIP → Brand detection → GPT-4o → Price Oracle → Moderation
//  Result card with condition/duration/price pickers
//  Publish: POST /listings → POST /listings/{id}/publish
// ═══════════════════════════════════════════════════════════════════════

/// Pipeline step definition — SDD §3.4.1.
class _PipelineStep {
  const _PipelineStep({
    required this.id,
    required this.label,
    required this.sublabel,
    required this.icon,
  });

  final String id;
  final String label;
  final String sublabel;
  final IconData icon;
}

const _steps = [
  _PipelineStep(
    id: 'clip',
    label: 'تحليل الصور',
    sublabel: 'CLIP ViT-B/32 — كشف المنتج والحالة',
    icon: Icons.image_search_rounded,
  ),
  _PipelineStep(
    id: 'brand',
    label: 'كشف العلامة التجارية',
    sublabel: 'Brand Detection — OCR + مطابقة',
    icon: Icons.branding_watermark_rounded,
  ),
  _PipelineStep(
    id: 'gpt',
    label: 'كتابة القائمة',
    sublabel: 'GPT-4o — عربي + إنجليزي',
    icon: Icons.auto_awesome_rounded,
  ),
  _PipelineStep(
    id: 'price',
    label: 'تقدير السعر',
    sublabel: 'Price Oracle — XGBoost',
    icon: Icons.price_change_rounded,
  ),
  _PipelineStep(
    id: 'moderation',
    label: 'مراجعة المحتوى',
    sublabel: 'Content Moderation — فلترة تلقائية',
    icon: Icons.verified_user_rounded,
  ),
];

enum _StepState { pending, running, done }

/// Result data from AI pipeline.
class SnapResult {
  const SnapResult({
    this.titleAr = '',
    this.titleEn = '',
    this.category = '',
    this.condition = '',
    this.priceLow = 0,
    this.priceHigh = 0,
    this.suggestedStart = 0,
    this.confidence = 0,
    this.currency = 'JOD',
    this.soldCount = 0,
  });

  final String titleAr;
  final String titleEn;
  final String category;
  final String condition;
  final double priceLow;
  final double priceHigh;
  final double suggestedStart;
  final double confidence;
  final String currency;
  final int soldCount;

  factory SnapResult.fromJson(Map<String, dynamic> json) => SnapResult(
        titleAr: json['title_ar'] as String? ?? '',
        titleEn: json['title_en'] as String? ?? '',
        category: json['category'] as String? ?? '',
        condition: json['condition'] as String? ?? '',
        priceLow: (json['price_low'] as num?)?.toDouble() ?? 0,
        priceHigh: (json['price_high'] as num?)?.toDouble() ?? 0,
        suggestedStart: (json['suggested_start'] as num?)?.toDouble() ?? 0,
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0,
        currency: json['currency'] as String? ?? 'JOD',
        soldCount: json['sold_count'] as int? ?? 0,
      );
}

class SnapToListScreen extends ConsumerStatefulWidget {
  const SnapToListScreen({
    super.key,
    this.imageKeys,
    this.draftId,
  });

  /// Pre-uploaded S3 keys (if coming from draft).
  final List<String>? imageKeys;

  /// Draft listing ID to resume editing.
  final String? draftId;

  @override
  ConsumerState<SnapToListScreen> createState() => _SnapToListScreenState();
}

class _SnapToListScreenState extends ConsumerState<SnapToListScreen>
    with TickerProviderStateMixin {
  // ── Photo capture ──────────────────────────────────────────────
  final _picker = ImagePicker();
  final List<XFile> _photos = [];
  List<String> _s3Keys = [];
  bool _isUploading = false;

  // ── Pipeline state ─────────────────────────────────────────────
  int _currentStepIndex = -1;
  final _stepStates = List.filled(_steps.length, _StepState.pending);
  bool _allDone = false;
  String? _error;
  SnapResult? _result;

  // ── Editable fields from result ────────────────────────────────
  String _selectedCondition = '';
  int _selectedDurationHours = 48;
  double _startPrice = 0;

  // ── Elapsed timer ──────────────────────────────────────────────
  final _stopwatch = Stopwatch();
  Timer? _elapsedTicker;
  int _elapsedMs = 0;

  // ── Running pulse animation ────────────────────────────────────
  late AnimationController _pulseController;
  late Animation<double> _pulseScale;

  // ── Done checkmark animation per step ──────────────────────────
  final List<AnimationController> _doneControllers = [];
  final List<Animation<double>> _doneScales = [];

  // ── Stepper header: connecting lines ───────────────────────────
  final List<AnimationController> _lineControllers = [];
  final List<Animation<double>> _lineProgress = [];

  // ── Progress bar ───────────────────────────────────────────────
  late AnimationController _progressController;

  // ── Result card entrance ───────────────────────────────────────
  late AnimationController _resultController;
  late Animation<double> _resultOpacity;
  late Animation<Offset> _resultSlide;

  // ── Publish CTA ────────────────────────────────────────────────
  late AnimationController _publishController;
  late Animation<double> _publishScale;
  late AnimationController _publishColorController;
  late Animation<Color?> _publishColor;
  bool _isPublishing = false;
  bool _publishSuccess = false;

  @override
  void initState() {
    super.initState();

    // Running pulse: 0.85 → 1.15
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _pulseScale = Tween<double>(begin: 0.85, end: 1.15).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    _pulseController.repeat(reverse: true);

    // Done checkmark elasticOut per step
    for (var i = 0; i < _steps.length; i++) {
      final c = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 500),
      );
      _doneControllers.add(c);
      _doneScales.add(
        Tween<double>(begin: 0.0, end: 1.0).animate(
          CurvedAnimation(parent: c, curve: Curves.elasticOut),
        ),
      );
    }

    // Connecting line controllers
    for (var i = 0; i < _steps.length - 1; i++) {
      final c = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 400),
      );
      _lineControllers.add(c);
      _lineProgress.add(
        CurvedAnimation(parent: c, curve: Curves.easeOutCubic),
      );
    }

    // Progress bar
    _progressController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );

    // Result card
    _resultController = AnimationController(
      vsync: this,
      duration: AppAnimations.enter,
    );
    _resultOpacity = CurvedAnimation(
        parent: _resultController, curve: Curves.easeOut);
    _resultSlide = Tween<Offset>(
      begin: const Offset(0, 0.25),
      end: Offset.zero,
    ).animate(CurvedAnimation(
        parent: _resultController, curve: Curves.easeOutCubic));

    // Publish CTA scale entrance
    _publishController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 350),
    );
    _publishScale = Tween<double>(begin: 0, end: 1).animate(
      CurvedAnimation(
          parent: _publishController, curve: Curves.easeOutBack),
    );

    // Publish color morph: gold → emerald
    _publishColorController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _publishColor = ColorTween(
      begin: AppColors.gold,
      end: AppColors.emerald,
    ).animate(CurvedAnimation(
        parent: _publishColorController, curve: Curves.easeOut));

    // If we already have image keys (from draft), skip photo capture
    if (widget.imageKeys != null && widget.imageKeys!.isNotEmpty) {
      _s3Keys = List.from(widget.imageKeys!);
      _startPipeline();
    }
  }

  @override
  void dispose() {
    _elapsedTicker?.cancel();
    _stopwatch.stop();
    _pulseController.dispose();
    for (final c in _doneControllers) {
      c.dispose();
    }
    for (final c in _lineControllers) {
      c.dispose();
    }
    _progressController.dispose();
    _resultController.dispose();
    _publishController.dispose();
    _publishColorController.dispose();
    super.dispose();
  }

  // ── Photo capture ─────────────────────────────────────────────────

  Future<void> _takePhoto() async {
    try {
      final photo = await _picker.pickImage(
        source: ImageSource.camera,
        imageQuality: 85,
      );
      if (photo != null && _photos.length < 10) {
        setState(() => _photos.add(photo));
      }
    } on PlatformException {
      if (!mounted) return;
      _showPermissionDialog();
    }
  }

  Future<void> _pickFromGallery() async {
    try {
      final photos = await _picker.pickMultiImage(imageQuality: 85);
      if (photos.isNotEmpty) {
        final remaining = 10 - _photos.length;
        setState(() {
          _photos.addAll(photos.take(remaining));
        });
      }
    } on PlatformException {
      if (!mounted) return;
      _showPermissionDialog();
    }
  }

  void _removePhoto(int index) {
    setState(() => _photos.removeAt(index));
  }

  void _showPermissionDialog() {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('إذن مطلوب'),
        content: const Text(
            'يرجى السماح بالوصول إلى الكاميرا أو المعرض من إعدادات التطبيق.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('حسنًا'),
          ),
        ],
      ),
    );
  }

  // ── S3 upload ─────────────────────────────────────────────────────

  Future<void> _uploadPhotosAndStart() async {
    if (_photos.isEmpty) return;
    setState(() => _isUploading = true);

    try {
      final api = ref.read(apiClientProvider);
      final keys = <String>[];

      for (final photo in _photos) {
        // Request presigned URL
        final resp = await api.post('/listings/images/request');
        final data = resp.data as Map<String, dynamic>;
        final presignedUrl = data['upload_url'] as String;
        final s3Key = data['s3_key'] as String;

        // Upload to S3
        final bytes = await File(photo.path).readAsBytes();
        await Dio().put(
          presignedUrl,
          data: bytes,
          options: Options(
            headers: {
              'Content-Type': 'image/jpeg',
              'Content-Length': bytes.length,
            },
          ),
        );
        keys.add(s3Key);
      }

      _s3Keys = keys;
      if (mounted) {
        setState(() => _isUploading = false);
        _startPipeline();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _isUploading = false;
          _error = 'فشل رفع الصور: ${e.toString()}';
        });
      }
    }
  }

  // ── Pipeline execution ────────────────────────────────────────────

  Future<void> _startPipeline() async {
    _stopwatch.start();
    _elapsedTicker = Timer.periodic(
      const Duration(milliseconds: 100),
      (_) {
        if (mounted) {
          setState(() => _elapsedMs = _stopwatch.elapsedMilliseconds);
        }
      },
    );

    try {
      final api = ref.read(apiClientProvider);

      // Call the snap-to-list API
      final future = api.post('/ai/snap-to-list', data: {
        's3_keys': _s3Keys,
      }).timeout(const Duration(seconds: 8));

      // Animate pipeline steps while waiting
      final stepFuture = _animateSteps();

      // Wait for both API and animation
      late final Response resp;
      try {
        final results = await Future.wait([future, stepFuture]);
        resp = results[0] as Response;
      } on TimeoutException {
        // Pipeline timeout — show partial result
        _stopwatch.stop();
        _elapsedTicker?.cancel();

        // Complete remaining steps as done visually
        for (var i = 0; i < _steps.length; i++) {
          if (_stepStates[i] != _StepState.done) {
            _stepStates[i] = _StepState.done;
            _doneControllers[i].forward();
            if (i < _lineControllers.length) {
              _lineControllers[i].forward();
            }
          }
        }
        _progressController.animateTo(1.0);

        if (mounted) {
          setState(() {
            _allDone = true;
            _error = 'انتهت مهلة التحليل — نتيجة جزئية';
          });
        }
        return;
      }

      _stopwatch.stop();
      _elapsedTicker?.cancel();

      if (!mounted) return;

      final data = resp.data as Map<String, dynamic>;
      final result = SnapResult.fromJson(data);

      setState(() {
        _allDone = true;
        _result = result;
        _selectedCondition = result.condition;
        _startPrice = result.suggestedStart;
      });

      AppHaptics.bidConfirmed();

      await Future.delayed(const Duration(milliseconds: 200));
      if (mounted) _resultController.forward();

      await Future.delayed(const Duration(milliseconds: 300));
      if (mounted) _publishController.forward();
    } catch (e) {
      _stopwatch.stop();
      _elapsedTicker?.cancel();
      if (mounted) setState(() => _error = e.toString());
    }
  }

  /// Animate pipeline steps sequentially while the API call is in progress.
  Future<void> _animateSteps() async {
    for (var i = 0; i < _steps.length; i++) {
      if (!mounted) return;

      setState(() {
        _currentStepIndex = i;
        _stepStates[i] = _StepState.running;
      });

      // Animate progress bar: 20% per step
      _progressController.animateTo(
        (i + 0.5) / _steps.length,
        duration: const Duration(milliseconds: 500),
        curve: Curves.easeOut,
      );

      // Wait for step animation (staggered timing)
      final delay = i == 2 ? 2500 : (i == 0 ? 800 : 500); // GPT step longer
      await Future.delayed(Duration(milliseconds: delay));
      if (!mounted) return;

      // Mark step done
      setState(() => _stepStates[i] = _StepState.done);
      _doneControllers[i].forward();
      HapticFeedback.selectionClick();

      // Draw connecting line
      if (i < _lineControllers.length) {
        _lineControllers[i].forward();
      }

      // Update progress to step end
      _progressController.animateTo(
        (i + 1) / _steps.length,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );

      if (i < _steps.length - 1) {
        await Future.delayed(const Duration(milliseconds: 150));
      }
    }
  }

  // ── Pickers ───────────────────────────────────────────────────────

  void _showConditionPicker() {
    final conditions = [
      'جديد',
      'ممتاز',
      'جيد جدًا',
      'جيد',
      'مقبول',
    ];
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(AppSpacing.md),
              child: Text(
                'حالة المنتج',
                style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy),
              ),
            ),
            ...conditions.map((c) => ListTile(
                  title: Text(c),
                  trailing: _selectedCondition == c
                      ? const Icon(Icons.check_rounded,
                          color: AppColors.emerald)
                      : null,
                  onTap: () {
                    setState(() => _selectedCondition = c);
                    Navigator.pop(context);
                  },
                )),
            const SizedBox(height: AppSpacing.md),
          ],
        ),
      ),
    );
  }

  void _showDurationPicker() {
    final durations = [12, 24, 48, 72, 120, 168];
    final labels = {
      12: '12 ساعة',
      24: 'يوم واحد',
      48: 'يومين',
      72: '3 أيام',
      120: '5 أيام',
      168: 'أسبوع',
    };
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Padding(
              padding: EdgeInsets.all(AppSpacing.md),
              child: Text(
                'مدة المزاد',
                style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy),
              ),
            ),
            ...durations.map((d) => ListTile(
                  title: Text(labels[d] ?? '$d ساعة'),
                  trailing: _selectedDurationHours == d
                      ? const Icon(Icons.check_rounded,
                          color: AppColors.emerald)
                      : null,
                  onTap: () {
                    setState(() => _selectedDurationHours = d);
                    Navigator.pop(context);
                  },
                )),
            const SizedBox(height: AppSpacing.md),
          ],
        ),
      ),
    );
  }

  void _showStartPricePicker() {
    final controller =
        TextEditingController(text: _startPrice.toStringAsFixed(0));
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (_) => Padding(
        padding: EdgeInsets.only(
          left: AppSpacing.md,
          right: AppSpacing.md,
          top: AppSpacing.md,
          bottom: MediaQuery.of(context).viewInsets.bottom + AppSpacing.md,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'سعر البداية',
              style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy),
            ),
            const SizedBox(height: AppSpacing.md),
            TextField(
              controller: controller,
              keyboardType: TextInputType.number,
              autofocus: true,
              decoration: InputDecoration(
                suffixText: _result?.currency ?? 'JOD',
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.navy,
                  foregroundColor: Colors.white,
                ),
                onPressed: () {
                  final val =
                      double.tryParse(controller.text) ?? _startPrice;
                  setState(() => _startPrice = val);
                  Navigator.pop(context);
                },
                child: const Text('تأكيد'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  // ── Publish ───────────────────────────────────────────────────────

  Future<void> _onPublish() async {
    if (_isPublishing || _result == null) return;

    setState(() => _isPublishing = true);
    AppHaptics.bidConfirmed();

    try {
      final api = ref.read(apiClientProvider);

      // Create draft listing
      final createResp = await api.post('/listings', data: {
        'title_ar': _result!.titleAr,
        'title_en': _result!.titleEn,
        'category': _result!.category,
        'condition': _selectedCondition,
        'start_price': _startPrice,
        'duration_hours': _selectedDurationHours,
        'currency': _result!.currency,
        's3_keys': _s3Keys,
      });

      final listingId =
          (createResp.data as Map<String, dynamic>)['id'] as String;

      // Publish the listing
      await api.post('/listings/$listingId/publish');

      if (!mounted) return;

      setState(() => _publishSuccess = true);
      _publishColorController.forward();

      await Future.delayed(const Duration(milliseconds: 800));
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      if (mounted) {
        setState(() => _isPublishing = false);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('فشل النشر: ${e.toString()}'),
            backgroundColor: AppColors.ember,
          ),
        );
      }
    }
  }

  // ── Build ─────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final showPhotoCapture =
        _s3Keys.isEmpty && _currentStepIndex < 0 && _error == null;

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        foregroundColor: AppColors.navy,
        title: const Text(
          'Snap-to-List',
          style: TextStyle(
            fontWeight: FontWeight.w700,
            fontFamily: 'Sora',
          ),
        ),
        centerTitle: true,
      ),
      body: SafeArea(
        child: showPhotoCapture ? _buildPhotoCapture() : _buildPipeline(),
      ),
    );
  }

  // ── Photo capture UI ──────────────────────────────────────────────

  Widget _buildPhotoCapture() {
    return Column(
      children: [
        Expanded(
          child: Padding(
            padding: AppSpacing.allMd,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'التقط صور المنتج',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  'حتى 10 صور • الذكاء الاصطناعي سيحلل المنتج',
                  style: TextStyle(
                    fontSize: 14,
                    color: AppColors.mist,
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),

                // Photo thumbnails
                if (_photos.isNotEmpty)
                  SizedBox(
                    height: 100,
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: _photos.length,
                      separatorBuilder: (_, __) =>
                          const SizedBox(width: AppSpacing.xs),
                      itemBuilder: (_, i) => Stack(
                        children: [
                          ClipRRect(
                            borderRadius: AppSpacing.radiusSm,
                            child: Image.file(
                              File(_photos[i].path),
                              width: 100,
                              height: 100,
                              fit: BoxFit.cover,
                            ),
                          ),
                          Positioned(
                            top: 4,
                            right: 4,
                            child: GestureDetector(
                              onTap: () => _removePhoto(i),
                              child: Container(
                                padding: const EdgeInsets.all(2),
                                decoration: const BoxDecoration(
                                  color: AppColors.ember,
                                  shape: BoxShape.circle,
                                ),
                                child: const Icon(Icons.close,
                                    color: Colors.white, size: 14),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),

                if (_photos.isNotEmpty) const SizedBox(height: AppSpacing.md),

                // Capture buttons
                Row(
                  children: [
                    Expanded(
                      child: _CaptureButton(
                        icon: Icons.camera_alt_rounded,
                        label: 'التقاط صورة',
                        onTap: _photos.length < 10 ? _takePhoto : null,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.md),
                    Expanded(
                      child: _CaptureButton(
                        icon: Icons.photo_library_rounded,
                        label: 'من المعرض',
                        onTap: _photos.length < 10 ? _pickFromGallery : null,
                      ),
                    ),
                  ],
                ),

                const SizedBox(height: AppSpacing.xs),
                Text(
                  '${_photos.length}/10 صور',
                  style: const TextStyle(
                      fontSize: 12, color: AppColors.mist),
                ),
              ],
            ),
          ),
        ),

        // Start analysis button
        if (_photos.isNotEmpty)
          Padding(
            padding: EdgeInsetsDirectional.only(
              start: AppSpacing.md,
              end: AppSpacing.md,
              bottom: AppSpacing.md,
            ),
            child: SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton(
                onPressed: _isUploading ? null : _uploadPhotosAndStart,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.gold,
                  foregroundColor: Colors.white,
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.radiusMd,
                  ),
                ),
                child: _isUploading
                    ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          valueColor:
                              AlwaysStoppedAnimation(Colors.white),
                        ),
                      )
                    : const Text(
                        'تحليل بالذكاء الاصطناعي',
                        style: TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600),
                      ),
              ),
            ),
          ),
      ],
    );
  }

  // ── Pipeline UI ───────────────────────────────────────────────────

  Widget _buildPipeline() {
    return Column(
      children: [
        // ── Stepper header ──────────────────────────────────────
        Padding(
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.xxl,
            vertical: AppSpacing.md,
          ),
          child: _buildStepperHeader(),
        ),

        // ── Progress bar ────────────────────────────────────────
        Padding(
          padding: AppSpacing.horizontalMd,
          child: AnimatedBuilder(
            animation: _progressController,
            builder: (_, __) => ClipRRect(
              borderRadius: AppSpacing.radiusFull,
              child: LinearProgressIndicator(
                value: _progressController.value,
                minHeight: 6,
                backgroundColor: AppColors.sand,
                valueColor: AlwaysStoppedAnimation(
                  _allDone ? AppColors.emerald : AppColors.navy,
                ),
              ),
            ),
          ),
        ),

        // ── Elapsed timer ───────────────────────────────────────
        Padding(
          padding: const EdgeInsetsDirectional.only(
              top: AppSpacing.sm, bottom: AppSpacing.xs),
          child: Text(
            _formatElapsed(_elapsedMs),
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: _allDone ? AppColors.emerald : AppColors.navy,
              fontFamily: 'Sora',
              fontFeatures: const [FontFeature.tabularFigures()],
            ),
          ),
        ),

        // ── Steps list ──────────────────────────────────────────
        Expanded(
          child: ListView.builder(
            padding: AppSpacing.allMd,
            itemCount: _steps.length +
                (_result != null ? 1 : 0) +
                (_error != null ? 1 : 0),
            itemBuilder: (_, i) {
              if (i < _steps.length) {
                return _StepTile(
                  step: _steps[i],
                  state: _stepStates[i],
                  doneScale: _doneScales[i],
                  pulseScale: _pulseScale,
                  pulseController: _pulseController,
                );
              }

              if (_error != null && i == _steps.length) {
                return _ErrorCard(error: _error!);
              }

              // Result card
              return FadeTransition(
                opacity: _resultOpacity,
                child: SlideTransition(
                  position: _resultSlide,
                  child: _ResultCard(
                    result: _result!,
                    selectedCondition: _selectedCondition,
                    selectedDurationHours: _selectedDurationHours,
                    startPrice: _startPrice,
                    onConditionTap: _showConditionPicker,
                    onDurationTap: _showDurationPicker,
                    onPriceTap: _showStartPricePicker,
                  ),
                ),
              );
            },
          ),
        ),

        // ── Publish CTA ─────────────────────────────────────────
        if (_allDone && _result != null)
          Padding(
            padding: EdgeInsetsDirectional.only(
              start: AppSpacing.md,
              end: AppSpacing.md,
              bottom: AppSpacing.md,
            ),
            child: ScaleTransition(
              scale: _publishScale,
              child: _PublishButton(
                isPublishing: _isPublishing,
                isSuccess: _publishSuccess,
                colorAnimation: _publishColor,
                colorController: _publishColorController,
                onTap: _onPublish,
              ),
            ),
          ),
      ],
    );
  }

  // ── Stepper header ────────────────────────────────────────────────

  Widget _buildStepperHeader() {
    // Show first 5 dots in compact mode
    return Row(
      children: List.generate(_steps.length * 2 - 1, (i) {
        if (i.isOdd) {
          final lineIndex = i ~/ 2;
          return Expanded(
            child: AnimatedBuilder(
              animation: lineIndex < _lineProgress.length
                  ? _lineProgress[lineIndex]
                  : const AlwaysStoppedAnimation(0.0),
              builder: (_, __) {
                final progress = lineIndex < _lineProgress.length
                    ? _lineProgress[lineIndex].value
                    : 0.0;
                return _StepperLine(
                  progress: progress,
                  isRtl: Directionality.of(context) == TextDirection.rtl,
                );
              },
            ),
          );
        }

        final stepIndex = i ~/ 2;
        final stepState = _stepStates[stepIndex];

        Widget circle = _StepperCircle(
          step: _steps[stepIndex],
          state: stepState,
          index: stepIndex + 1,
        );

        if (stepState == _StepState.done) {
          circle = AnimatedBuilder(
            animation: _doneScales[stepIndex],
            builder: (_, child) => Transform.scale(
              scale: _doneScales[stepIndex].value.clamp(0.0, 2.0),
              child: child,
            ),
            child: circle,
          );
        } else if (stepState == _StepState.running) {
          circle = AnimatedBuilder(
            animation: _pulseScale,
            builder: (_, child) => Transform.scale(
              scale: _pulseScale.value,
              child: child,
            ),
            child: circle,
          );
        }

        return circle;
      }),
    );
  }

  String _formatElapsed(int ms) {
    final seconds = ms ~/ 1000;
    final tenths = (ms % 1000) ~/ 100;
    return '$seconds.${tenths}s';
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Capture button
// ═══════════════════════════════════════════════════════════════════════

class _CaptureButton extends StatelessWidget {
  const _CaptureButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: onTap == null ? AppColors.sand.withOpacity(0.5) : Colors.white,
      borderRadius: AppSpacing.radiusMd,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppSpacing.radiusMd,
        child: Container(
          padding: AppSpacing.allMd,
          decoration: BoxDecoration(
            borderRadius: AppSpacing.radiusMd,
            border: Border.all(
              color: AppColors.sand,
            ),
          ),
          child: Column(
            children: [
              Icon(icon,
                  color: onTap == null ? AppColors.mist : AppColors.navy,
                  size: 32),
              const SizedBox(height: AppSpacing.xs),
              Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: onTap == null ? AppColors.mist : AppColors.navy,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Stepper circle
// ═══════════════════════════════════════════════════════════════════════

class _StepperCircle extends StatelessWidget {
  const _StepperCircle({
    required this.step,
    required this.state,
    required this.index,
  });

  final _PipelineStep step;
  final _StepState state;
  final int index;

  @override
  Widget build(BuildContext context) {
    final Color bg;
    final Widget content;

    switch (state) {
      case _StepState.done:
        bg = AppColors.emerald;
        content = const Icon(Icons.check_rounded, color: Colors.white, size: 14);
      case _StepState.running:
        bg = AppColors.gold;
        content = const Icon(Icons.circle, color: Colors.white, size: 8);
      case _StepState.pending:
        bg = AppColors.sand;
        content = Text(
          '$index',
          style: const TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w700,
            color: AppColors.mist,
            fontFamily: 'Sora',
          ),
        );
    }

    return Container(
      width: 28,
      height: 28,
      decoration: BoxDecoration(
        color: bg,
        shape: BoxShape.circle,
      ),
      child: Center(child: content),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Stepper connecting line
// ═══════════════════════════════════════════════════════════════════════

class _StepperLine extends StatelessWidget {
  const _StepperLine({required this.progress, required this.isRtl});
  final double progress;
  final bool isRtl;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 3,
      child: CustomPaint(
        painter: _LinePainter(progress: progress, isRtl: isRtl),
        size: Size.infinite,
      ),
    );
  }
}

class _LinePainter extends CustomPainter {
  _LinePainter({required this.progress, required this.isRtl});
  final double progress;
  final bool isRtl;

  @override
  void paint(Canvas canvas, Size size) {
    final bgPaint = Paint()
      ..color = AppColors.sand
      ..strokeWidth = 3;
    final fgPaint = Paint()
      ..color = AppColors.emerald
      ..strokeWidth = 3;

    final y = size.height / 2;
    canvas.drawLine(Offset(0, y), Offset(size.width, y), bgPaint);

    if (progress > 0) {
      final w = size.width * progress;
      if (isRtl) {
        canvas.drawLine(
            Offset(size.width, y), Offset(size.width - w, y), fgPaint);
      } else {
        canvas.drawLine(Offset(0, y), Offset(w, y), fgPaint);
      }
    }
  }

  @override
  bool shouldRepaint(_LinePainter old) => progress != old.progress;
}

// ═══════════════════════════════════════════════════════════════════════
//  Step tile
// ═══════════════════════════════════════════════════════════════════════

class _StepTile extends StatelessWidget {
  const _StepTile({
    required this.step,
    required this.state,
    required this.doneScale,
    required this.pulseScale,
    required this.pulseController,
  });

  final _PipelineStep step;
  final _StepState state;
  final Animation<double> doneScale;
  final Animation<double> pulseScale;
  final AnimationController pulseController;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.md),
      child: AnimatedContainer(
        duration: AppAnimations.state,
        curve: AppAnimations.enterCurve,
        padding: AppSpacing.allMd,
        decoration: BoxDecoration(
          color: state == _StepState.done
              ? AppColors.emerald.withOpacity(0.05)
              : state == _StepState.running
                  ? Colors.white
                  : AppColors.sand.withOpacity(0.2),
          borderRadius: AppSpacing.radiusMd,
          border: Border.all(
            color: state == _StepState.done
                ? AppColors.emerald.withOpacity(0.2)
                : state == _StepState.running
                    ? AppColors.gold.withOpacity(0.3)
                    : Colors.transparent,
          ),
        ),
        child: Row(
          children: [
            _buildIcon(),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    step.label,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: state == _StepState.pending
                          ? AppColors.mist
                          : state == _StepState.done
                              ? AppColors.emerald
                              : AppColors.navy,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    step.sublabel,
                    style: TextStyle(
                      fontSize: 12,
                      color: state == _StepState.pending
                          ? AppColors.mist.withOpacity(0.5)
                          : AppColors.mist,
                    ),
                  ),
                ],
              ),
            ),
            if (state == _StepState.running)
              AnimatedBuilder(
                animation: pulseController,
                builder: (_, child) => Transform.scale(
                  scale: pulseScale.value,
                  child: child,
                ),
                child: Container(
                  width: 12,
                  height: 12,
                  decoration: const BoxDecoration(
                    color: AppColors.gold,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
            if (state == _StepState.done)
              const Icon(Icons.check_rounded,
                  color: AppColors.emerald, size: 20),
          ],
        ),
      ),
    );
  }

  Widget _buildIcon() {
    switch (state) {
      case _StepState.done:
        return AnimatedBuilder(
          animation: doneScale,
          builder: (_, child) => Transform.scale(
            scale: doneScale.value.clamp(0.0, 2.0),
            child: child,
          ),
          child: Container(
            width: 36,
            height: 36,
            decoration: const BoxDecoration(
              color: AppColors.emerald,
              shape: BoxShape.circle,
            ),
            child:
                const Icon(Icons.check_rounded, color: Colors.white, size: 18),
          ),
        );
      case _StepState.running:
        return AnimatedBuilder(
          animation: pulseController,
          builder: (_, child) => Transform.scale(
            scale: pulseScale.value,
            child: child,
          ),
          child: Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppColors.gold.withOpacity(0.15),
              shape: BoxShape.circle,
            ),
            child: Icon(step.icon, color: AppColors.gold, size: 18),
          ),
        );
      case _StepState.pending:
        return Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppColors.sand,
            shape: BoxShape.circle,
          ),
          child: Icon(step.icon, color: AppColors.mist, size: 18),
        );
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Result card
// ═══════════════════════════════════════════════════════════════════════

class _ResultCard extends StatelessWidget {
  const _ResultCard({
    required this.result,
    required this.selectedCondition,
    required this.selectedDurationHours,
    required this.startPrice,
    required this.onConditionTap,
    required this.onDurationTap,
    required this.onPriceTap,
  });

  final SnapResult result;
  final String selectedCondition;
  final int selectedDurationHours;
  final double startPrice;
  final VoidCallback onConditionTap;
  final VoidCallback onDurationTap;
  final VoidCallback onPriceTap;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsetsDirectional.only(top: AppSpacing.md),
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: AppSpacing.radiusMd,
        border: Border.all(color: AppColors.emerald.withOpacity(0.2)),
        boxShadow: [
          BoxShadow(
            color: AppColors.emerald.withOpacity(0.08),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header
          Row(
            children: [
              const Icon(Icons.auto_awesome_rounded,
                  color: AppColors.emerald, size: 20),
              const SizedBox(width: AppSpacing.xs),
              const Text(
                'نتيجة التحليل',
                style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                  color: AppColors.emerald,
                ),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsetsDirectional.symmetric(
                    horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppColors.emerald.withOpacity(0.1),
                  borderRadius: AppSpacing.radiusSm,
                ),
                child: Text(
                  'ثقة ${(result.confidence * 100).round()}%',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppColors.emerald,
                  ),
                ),
              ),
            ],
          ),

          const SizedBox(height: AppSpacing.md),

          // Arabic title — RTL
          Directionality(
            textDirection: TextDirection.rtl,
            child: Text(
              result.titleAr,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppColors.ink,
                fontFamily: 'NotoKufiArabic',
              ),
            ),
          ),
          const SizedBox(height: 2),
          Text(
            result.titleEn,
            style: const TextStyle(fontSize: 13, color: AppColors.mist),
          ),

          const SizedBox(height: AppSpacing.md),

          // Category + Condition (tappable)
          Row(
            children: [
              _ResultChip(label: result.category, color: AppColors.navy),
              const SizedBox(width: AppSpacing.xs),
              GestureDetector(
                onTap: onConditionTap,
                child: _ResultChip(
                  label: selectedCondition.isNotEmpty
                      ? selectedCondition
                      : result.condition,
                  color: AppColors.emerald,
                  trailing: const Icon(Icons.edit_rounded,
                      size: 12, color: AppColors.emerald),
                ),
              ),
            ],
          ),

          const SizedBox(height: AppSpacing.md),

          // Price range with confidence
          Container(
            width: double.infinity,
            padding: AppSpacing.allSm,
            decoration: BoxDecoration(
              color: AppColors.gold.withOpacity(0.06),
              borderRadius: AppSpacing.radiusMd,
            ),
            child: Column(
              children: [
                const Text(
                  'نطاق السعر المقترح',
                  style: TextStyle(fontSize: 12, color: AppColors.mist),
                ),
                const SizedBox(height: 4),
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      ArabicNumerals.formatCurrency(
                          result.priceLow, result.currency),
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: AppColors.gold,
                        fontFamily: 'Sora',
                      ),
                    ),
                    const Text(' — ',
                        style: TextStyle(color: AppColors.mist)),
                    Text(
                      ArabicNumerals.formatCurrency(
                          result.priceHigh, result.currency),
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: AppColors.gold,
                        fontFamily: 'Sora',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  'High confidence · Based on ${result.soldCount} sold',
                  style: const TextStyle(
                    fontSize: 11,
                    color: AppColors.mist,
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: AppSpacing.md),

          // Editable fields: duration + start price
          Row(
            children: [
              Expanded(
                child: _EditableField(
                  label: 'المدة',
                  value: _durationLabel(selectedDurationHours),
                  onTap: onDurationTap,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: _EditableField(
                  label: 'سعر البداية',
                  value: ArabicNumerals.formatCurrency(
                      startPrice, result.currency),
                  onTap: onPriceTap,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  String _durationLabel(int hours) {
    if (hours <= 12) return '12 ساعة';
    if (hours <= 24) return 'يوم واحد';
    if (hours <= 48) return 'يومين';
    if (hours <= 72) return '3 أيام';
    if (hours <= 120) return '5 أيام';
    return 'أسبوع';
  }
}

class _ResultChip extends StatelessWidget {
  const _ResultChip({
    required this.label,
    required this.color,
    this.trailing,
  });
  final String label;
  final Color color;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding:
          const EdgeInsetsDirectional.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.1),
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: color,
            ),
          ),
          if (trailing != null) ...[
            const SizedBox(width: 4),
            trailing!,
          ],
        ],
      ),
    );
  }
}

class _EditableField extends StatelessWidget {
  const _EditableField({
    required this.label,
    required this.value,
    required this.onTap,
  });

  final String label;
  final String value;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: AppSpacing.allSm,
        decoration: BoxDecoration(
          color: AppColors.sand.withOpacity(0.3),
          borderRadius: AppSpacing.radiusSm,
          border: Border.all(color: AppColors.sand),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(fontSize: 11, color: AppColors.mist),
            ),
            const SizedBox(height: 2),
            Row(
              children: [
                Expanded(
                  child: Text(
                    value,
                    style: const TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.navy,
                    ),
                  ),
                ),
                const Icon(Icons.edit_rounded,
                    size: 14, color: AppColors.mist),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Error card
// ═══════════════════════════════════════════════════════════════════════

class _ErrorCard extends StatelessWidget {
  const _ErrorCard({required this.error});
  final String error;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsetsDirectional.only(top: AppSpacing.md),
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: AppColors.ember.withOpacity(0.06),
        borderRadius: AppSpacing.radiusMd,
        border: Border.all(color: AppColors.ember.withOpacity(0.2)),
      ),
      child: Row(
        children: [
          const Icon(Icons.error_outline_rounded,
              color: AppColors.ember, size: 20),
          const SizedBox(width: AppSpacing.xs),
          Expanded(
            child: Text(
              error,
              style: const TextStyle(fontSize: 13, color: AppColors.ember),
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Publish CTA — ColorTween gold→emerald, loading state
// ═══════════════════════════════════════════════════════════════════════

class _PublishButton extends StatelessWidget {
  const _PublishButton({
    required this.isPublishing,
    required this.isSuccess,
    required this.colorAnimation,
    required this.colorController,
    required this.onTap,
  });

  final bool isPublishing;
  final bool isSuccess;
  final Animation<Color?> colorAnimation;
  final AnimationController colorController;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 52,
      child: AnimatedBuilder(
        animation: colorController,
        builder: (_, __) => Container(
          decoration: BoxDecoration(
            color: colorAnimation.value ?? AppColors.gold,
            borderRadius: AppSpacing.radiusMd,
          ),
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              onTap: isPublishing || isSuccess ? null : onTap,
              borderRadius: AppSpacing.radiusMd,
              splashFactory: InkRipple.splashFactory,
              child: Center(
                child: AnimatedSwitcher(
                  duration: AppAnimations.state,
                  child: isSuccess
                      ? const Icon(Icons.check_rounded,
                          key: ValueKey('done'),
                          color: Colors.white,
                          size: 28)
                      : isPublishing
                          ? const SizedBox(
                              key: ValueKey('loading'),
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                valueColor:
                                    AlwaysStoppedAnimation(Colors.white),
                              ),
                            )
                          : const Text(
                              'نشر القائمة',
                              key: ValueKey('publish'),
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
        ),
      ),
    );
  }
}
