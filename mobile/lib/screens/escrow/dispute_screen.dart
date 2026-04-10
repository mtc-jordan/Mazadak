import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/providers/core_providers.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';

/// Dispute screen — 3-step wizard reached from EscrowOrderScreen.
///
/// Step 1: Reason selection
/// Step 2: Evidence upload (photos + text)
/// Step 3: Review & submit
class DisputeScreen extends ConsumerStatefulWidget {
  const DisputeScreen({super.key, required this.escrowId});

  final String escrowId;

  @override
  ConsumerState<DisputeScreen> createState() => _DisputeScreenState();
}

class _DisputeScreenState extends ConsumerState<DisputeScreen>
    with TickerProviderStateMixin {
  int _step = 0; // 0-indexed: 0=reason, 1=evidence, 2=review

  // ── Step 1 state ──────────────────────────────────────────────
  int? _selectedReasonIndex;

  // ── Step 2 state ──────────────────────────────────────────────
  final List<_EvidencePhoto> _photos = [];
  final _descController = TextEditingController();
  final _descFocusNode = FocusNode();
  final _picker = ImagePicker();

  static const _maxPhotos = 10;
  static const _maxSizeBytes = 5 * 1024 * 1024; // 5MB
  static const _minDescChars = 50;
  static const _maxDescChars = 500;

  // ── Step 3 state ──────────────────────────────────────────────
  int _resolutionIndex = 0; // 0=full refund, 1=partial, 2=replacement
  bool _submitting = false;
  bool _submitted = false;

  // ── CTA animation ─────────────────────────────────────────────
  late final AnimationController _ctaController;
  late final Animation<double> _ctaScale;

  // ── Success animation ─────────────────────────────────────────
  late final AnimationController _successController;
  late final Animation<double> _successScale;
  late final AnimationController _checkController;

  static const _reasons = [
    (
      title: 'Item not as described',
      subtitle: 'Condition, specs, or photos didn\'t match',
    ),
    (
      title: 'Item not received',
      subtitle: 'Seller hasn\'t shipped after 48h',
    ),
    (
      title: 'Item damaged',
      subtitle: 'Arrived broken or damaged in transit',
    ),
    (
      title: 'Counterfeit item',
      subtitle: 'Item is not authentic as claimed',
    ),
    (
      title: 'Wrong item received',
      subtitle: 'Different item than what was listed',
    ),
    (
      title: 'Other',
      subtitle: 'Describe your issue',
    ),
  ];

  static const _resolutions = [
    (title: 'Full refund', icon: Icons.payments_rounded),
    (title: 'Partial refund', icon: Icons.price_change_rounded),
    (title: 'Replacement', icon: Icons.swap_horiz_rounded),
  ];

  @override
  void initState() {
    super.initState();
    _ctaController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _ctaScale = CurvedAnimation(
      parent: _ctaController,
      curve: Curves.elasticOut,
    );

    _successController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _successScale = CurvedAnimation(
      parent: _successController,
      curve: Curves.elasticOut,
    );

    _checkController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    _descController.addListener(_onDescChanged);
  }

  @override
  void dispose() {
    _ctaController.dispose();
    _successController.dispose();
    _checkController.dispose();
    _descController.dispose();
    _descFocusNode.dispose();
    super.dispose();
  }

  void _onDescChanged() => setState(() {});

  // ── Navigation ────────────────────────────────────────────────

  bool get _canContinue => switch (_step) {
        0 => _selectedReasonIndex != null,
        1 => _photos.isNotEmpty && _descController.text.length >= _minDescChars,
        2 => true,
        _ => false,
      };

  void _next() {
    if (_step < 2) {
      setState(() => _step++);
      _ctaController.reset();
    } else {
      _submit();
    }
  }

  void _back() {
    if (_step > 0) {
      setState(() => _step--);
    } else {
      Navigator.of(context).maybePop();
    }
  }

  // ── Photo handling ────────────────────────────────────────────

  Future<void> _pickFromCamera() async {
    if (_photos.length >= _maxPhotos) {
      _showMaxPhotosSnackbar();
      return;
    }
    try {
      final photo = await _picker.pickImage(
        source: ImageSource.camera,
        maxWidth: 1920,
        maxHeight: 1920,
        imageQuality: 85,
      );
      if (photo != null) await _addPhoto(photo);
    } on PlatformException {
      // permission denied — ignore
    }
  }

  Future<void> _pickFromGallery() async {
    final remaining = _maxPhotos - _photos.length;
    if (remaining <= 0) {
      _showMaxPhotosSnackbar();
      return;
    }
    try {
      final photos = await _picker.pickMultiImage(
        maxWidth: 1920,
        maxHeight: 1920,
        imageQuality: 85,
      );
      for (final photo in photos.take(remaining)) {
        await _addPhoto(photo);
      }
    } on PlatformException {
      // permission denied — ignore
    }
  }

  Future<void> _addPhoto(XFile photo) async {
    final size = await photo.length();
    if (size > _maxSizeBytes) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Photo exceeds 5MB limit'),
          backgroundColor: AppColors.ember,
        ),
      );
      return;
    }

    // Compute SHA-256 hash
    final bytes = await photo.readAsBytes();
    final hash = sha256.convert(bytes).toString();

    setState(() {
      _photos.add(_EvidencePhoto(file: photo, hash: hash));
    });
  }

  void _removePhoto(int index) {
    setState(() => _photos.removeAt(index));
  }

  void _showMaxPhotosSnackbar() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('Maximum 10 photos allowed'),
        backgroundColor: AppColors.ember,
      ),
    );
  }

  // ── Submit ────────────────────────────────────────────────────

  Future<void> _submit() async {
    if (_submitting) return;
    HapticFeedback.mediumImpact();
    setState(() => _submitting = true);

    try {
      final api = ref.read(apiClientProvider);
      final formData = FormData();

      formData.fields.add(MapEntry(
        'reason',
        _reasons[_selectedReasonIndex!].title,
      ));
      formData.fields.add(MapEntry(
        'description',
        _descController.text,
      ));
      formData.fields.add(MapEntry(
        'resolution',
        _resolutions[_resolutionIndex].title,
      ));

      for (final evidence in _photos) {
        final bytes = await evidence.file.readAsBytes();
        formData.fields.add(MapEntry('hashes[]', evidence.hash));
        formData.files.add(MapEntry(
          'photos[]',
          MultipartFile.fromBytes(bytes, filename: evidence.file.name),
        ));
      }

      await api.post(
        '/disputes',
        data: formData,
        options: Options(contentType: 'multipart/form-data'),
      );

      if (!mounted) return;
      setState(() => _submitted = true);
      _successController.forward();
      _checkController.forward();

      // Navigate back after success animation
      await Future.delayed(const Duration(milliseconds: 1500));
      if (mounted) {
        context.pop();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Failed to submit: ${e.toString().split(':').last.trim()}'),
          backgroundColor: AppColors.ember,
        ),
      );
    }
  }

  // ── Build ─────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    // Full-screen success overlay
    if (_submitted) {
      return Scaffold(
        backgroundColor: AppColors.cream,
        body: Center(
          child: ScaleTransition(
            scale: _successScale,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 96,
                  height: 96,
                  decoration: const BoxDecoration(
                    color: AppColors.emerald,
                    shape: BoxShape.circle,
                  ),
                  child: AnimatedBuilder(
                    animation: _checkController,
                    builder: (_, __) => CustomPaint(
                      painter: _CheckPainter(
                        progress: _checkController.value,
                        color: Colors.white,
                        strokeWidth: 4,
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: AppSpacing.lg),
                const Text(
                  'Dispute submitted',
                  style: TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 22,
                    fontWeight: FontWeight.w800,
                    color: AppColors.navy,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                const Text(
                  'تم تقديم النزاع بنجاح',
                  style: TextStyle(
                    fontSize: 16,
                    color: AppColors.mist,
                  ),
                ),
                const SizedBox(height: AppSpacing.sm),
                const Text(
                  'Our team will review within 72 hours',
                  style: TextStyle(
                    fontSize: 14,
                    color: AppColors.mist,
                  ),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
          onPressed: _back,
        ),
        title: const Column(
          children: [
            Text(
              'Report a problem',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'الإبلاغ عن مشكلة',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        centerTitle: true,
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(4),
          child: _ProgressBar(step: _step, totalSteps: 3),
        ),
      ),
      body: Column(
        children: [
          // Scrollable step content
          Expanded(
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 250),
              switchInCurve: Curves.easeOutCubic,
              switchOutCurve: Curves.easeIn,
              transitionBuilder: (child, animation) {
                return FadeTransition(
                  opacity: animation,
                  child: SlideTransition(
                    position: Tween<Offset>(
                      begin: const Offset(0.05, 0),
                      end: Offset.zero,
                    ).animate(animation),
                    child: child,
                  ),
                );
              },
              child: switch (_step) {
                0 => _ReasonStep(
                    key: const ValueKey('step-0'),
                    selectedIndex: _selectedReasonIndex,
                    onSelect: (i) {
                      HapticFeedback.selectionClick();
                      setState(() => _selectedReasonIndex = i);
                      if (_ctaController.status != AnimationStatus.completed) {
                        _ctaController.forward();
                      }
                    },
                  ),
                1 => _EvidenceStep(
                    key: const ValueKey('step-1'),
                    photos: _photos,
                    descController: _descController,
                    descFocusNode: _descFocusNode,
                    maxPhotos: _maxPhotos,
                    minDescChars: _minDescChars,
                    maxDescChars: _maxDescChars,
                    onPickCamera: _pickFromCamera,
                    onPickGallery: _pickFromGallery,
                    onRemovePhoto: _removePhoto,
                  ),
                2 => _ReviewStep(
                    key: const ValueKey('step-2'),
                    reason: _reasons[_selectedReasonIndex!],
                    photoCount: _photos.length,
                    description: _descController.text,
                    resolutionIndex: _resolutionIndex,
                    onResolutionChanged: (i) =>
                        setState(() => _resolutionIndex = i),
                  ),
                _ => const SizedBox.shrink(),
              },
            ),
          ),

          // CTA button
          _BottomCta(
            step: _step,
            canContinue: _canContinue,
            submitting: _submitting,
            ctaScale: _step == 0 ? _ctaScale : null,
            onTap: _canContinue ? _next : null,
          ),
        ],
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Step 1 — Reason selection
// ══════════════════════════════════════════════════════════════════

class _ReasonStep extends StatelessWidget {
  const _ReasonStep({
    super.key,
    required this.selectedIndex,
    required this.onSelect,
  });

  final int? selectedIndex;
  final ValueChanged<int> onSelect;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsetsDirectional.all(20),
      children: [
        const Text(
          'What went wrong?',
          style: TextStyle(
            fontFamily: 'Sora',
            fontSize: 20,
            fontWeight: FontWeight.w800,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        ...List.generate(_DisputeScreenState._reasons.length, (i) {
          final reason = _DisputeScreenState._reasons[i];
          final isSelected = selectedIndex == i;

          return Padding(
            padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
            child: GestureDetector(
              onTap: () => onSelect(i),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                curve: Curves.easeOutCubic,
                padding: AppSpacing.allMd,
                decoration: BoxDecoration(
                  color: isSelected ? AppColors.cream : Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: isSelected ? AppColors.navy : AppColors.sand,
                    width: 1.5,
                  ),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            reason.title,
                            style: TextStyle(
                              fontFamily: 'Sora',
                              fontSize: 15,
                              fontWeight:
                                  isSelected ? FontWeight.w700 : FontWeight.w600,
                              color: AppColors.navy,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            reason.subtitle,
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.mist,
                            ),
                          ),
                        ],
                      ),
                    ),
                    AnimatedOpacity(
                      duration: const Duration(milliseconds: 200),
                      opacity: isSelected ? 1.0 : 0.0,
                      child: const Icon(
                        Icons.check_circle_rounded,
                        color: AppColors.navy,
                        size: 22,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }),
      ],
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Step 2 — Evidence upload
// ══════════════════════════════════════════════════════════════════

class _EvidenceStep extends StatelessWidget {
  const _EvidenceStep({
    super.key,
    required this.photos,
    required this.descController,
    required this.descFocusNode,
    required this.maxPhotos,
    required this.minDescChars,
    required this.maxDescChars,
    required this.onPickCamera,
    required this.onPickGallery,
    required this.onRemovePhoto,
  });

  final List<_EvidencePhoto> photos;
  final TextEditingController descController;
  final FocusNode descFocusNode;
  final int maxPhotos;
  final int minDescChars;
  final int maxDescChars;
  final VoidCallback onPickCamera;
  final VoidCallback onPickGallery;
  final ValueChanged<int> onRemovePhoto;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsetsDirectional.all(20),
      children: [
        // Header
        const Text(
          'Add evidence',
          style: TextStyle(
            fontFamily: 'Sora',
            fontSize: 18,
            fontWeight: FontWeight.w800,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: 2),
        const Text(
          'أضف الأدلة',
          style: TextStyle(
            fontFamily: 'Sora',
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: AppColors.mist,
          ),
        ),
        const SizedBox(height: AppSpacing.xs),
        const Text(
          'Photos help us resolve faster — minimum 1 required',
          style: TextStyle(fontSize: 13, color: AppColors.mist),
        ),
        const SizedBox(height: AppSpacing.lg),

        // Photo grid — 3 columns
        _PhotoGrid(
          photos: photos,
          maxPhotos: maxPhotos,
          onPickCamera: onPickCamera,
          onPickGallery: onPickGallery,
          onRemove: onRemovePhoto,
        ),

        const SizedBox(height: AppSpacing.xl),

        // Text description
        Text(
          'Describe the issue in detail · اشرح المشكلة بالتفصيل',
          style: TextStyle(
            fontFamily: 'Sora',
            fontSize: 14,
            fontWeight: FontWeight.w600,
            color: AppColors.navy.withOpacity(0.8),
          ),
        ),
        const SizedBox(height: AppSpacing.xs),
        _DescriptionField(
          controller: descController,
          focusNode: descFocusNode,
          minChars: minDescChars,
          maxChars: maxDescChars,
        ),
      ],
    );
  }
}

class _PhotoGrid extends StatelessWidget {
  const _PhotoGrid({
    required this.photos,
    required this.maxPhotos,
    required this.onPickCamera,
    required this.onPickGallery,
    required this.onRemove,
  });

  final List<_EvidencePhoto> photos;
  final int maxPhotos;
  final VoidCallback onPickCamera;
  final VoidCallback onPickGallery;
  final ValueChanged<int> onRemove;

  @override
  Widget build(BuildContext context) {
    final cellCount = (photos.length < maxPhotos) ? photos.length + 1 : photos.length;

    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 3,
        mainAxisSpacing: AppSpacing.xs,
        crossAxisSpacing: AppSpacing.xs,
        childAspectRatio: 1,
      ),
      itemCount: cellCount,
      itemBuilder: (_, i) {
        if (i < photos.length) {
          return _FilledCell(
            photo: photos[i],
            onRemove: () => onRemove(i),
          );
        }
        // Empty add cell
        return _EmptyCell(
          onPickCamera: onPickCamera,
          onPickGallery: onPickGallery,
        );
      },
    );
  }
}

class _FilledCell extends StatelessWidget {
  const _FilledCell({required this.photo, required this.onRemove});

  final _EvidencePhoto photo;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Image.file(
            File(photo.file.path),
            fit: BoxFit.cover,
          ),
        ),
        // Hash overlay at bottom
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
            decoration: BoxDecoration(
              color: Colors.black.withOpacity(0.6),
              borderRadius: const BorderRadius.vertical(
                bottom: Radius.circular(10),
              ),
            ),
            child: Text(
              '#${photo.hash.substring(0, 8)}',
              style: const TextStyle(
                fontFamily: 'Sora',
                fontSize: 9,
                fontWeight: FontWeight.w500,
                color: Colors.white70,
                letterSpacing: 0.5,
              ),
              textAlign: TextAlign.center,
            ),
          ),
        ),
        // Remove button
        PositionedDirectional(
          top: 4,
          end: 4,
          child: GestureDetector(
            onTap: onRemove,
            child: Container(
              width: 24,
              height: 24,
              decoration: BoxDecoration(
                color: AppColors.ember.withOpacity(0.9),
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withOpacity(0.2),
                    blurRadius: 4,
                  ),
                ],
              ),
              child: const Icon(Icons.close_rounded, color: Colors.white, size: 14),
            ),
          ),
        ),
      ],
    );
  }
}

class _EmptyCell extends StatelessWidget {
  const _EmptyCell({
    required this.onPickCamera,
    required this.onPickGallery,
  });

  final VoidCallback onPickCamera;
  final VoidCallback onPickGallery;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => _showPicker(context),
      child: CustomPaint(
        painter: _DashedBorderPainter(
          color: AppColors.sand,
          strokeWidth: 1.5,
          radius: 10,
        ),
        child: Container(
          decoration: BoxDecoration(
            color: AppColors.cream,
            borderRadius: BorderRadius.circular(10),
          ),
          child: const Center(
            child: Icon(
              Icons.add_rounded,
              color: AppColors.mist,
              size: 28,
            ),
          ),
        ),
      ),
    );
  }

  void _showPicker(BuildContext context) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.camera_alt_rounded, color: AppColors.navy),
              title: const Text('Camera'),
              onTap: () {
                Navigator.pop(context);
                onPickCamera();
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_rounded, color: AppColors.navy),
              title: const Text('Gallery'),
              onTap: () {
                Navigator.pop(context);
                onPickGallery();
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _DescriptionField extends StatelessWidget {
  const _DescriptionField({
    required this.controller,
    required this.focusNode,
    required this.minChars,
    required this.maxChars,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final int minChars;
  final int maxChars;

  @override
  Widget build(BuildContext context) {
    final length = controller.text.length;
    final belowMin = length > 0 && length < minChars;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        TextField(
          controller: controller,
          focusNode: focusNode,
          minLines: 3,
          maxLines: 8,
          maxLength: maxChars,
          buildCounter: (_, {required currentLength, required isFocused, maxLength}) =>
              null,
          style: const TextStyle(fontSize: 14, color: AppColors.ink),
          decoration: InputDecoration(
            hintText: 'Explain what happened...',
            hintStyle: const TextStyle(color: AppColors.mist, fontSize: 14),
            filled: true,
            fillColor: Colors.white,
            contentPadding: AppSpacing.allMd,
            enabledBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: AppColors.sand, width: 1.5),
            ),
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: const BorderSide(color: AppColors.navy, width: 1.5),
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.xxs),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            if (belowMin)
              Text(
                '${minChars - length} more characters needed',
                style: const TextStyle(fontSize: 11, color: AppColors.ember),
              )
            else
              const SizedBox.shrink(),
            Text(
              '$length/$maxChars',
              style: TextStyle(
                fontSize: 11,
                color: belowMin ? AppColors.ember : AppColors.mist,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Step 3 — Review & submit
// ══════════════════════════════════════════════════════════════════

class _ReviewStep extends StatelessWidget {
  const _ReviewStep({
    super.key,
    required this.reason,
    required this.photoCount,
    required this.description,
    required this.resolutionIndex,
    required this.onResolutionChanged,
  });

  final ({String title, String subtitle}) reason;
  final int photoCount;
  final String description;
  final int resolutionIndex;
  final ValueChanged<int> onResolutionChanged;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsetsDirectional.all(20),
      children: [
        // Summary card
        Container(
          padding: AppSpacing.allMd,
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.sand, width: 1),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Summary',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
              const SizedBox(height: AppSpacing.sm),
              _SummaryRow(
                label: 'Reason',
                value: reason.title,
              ),
              const SizedBox(height: AppSpacing.xs),
              _SummaryRow(
                label: 'Evidence',
                value: '$photoCount photo${photoCount == 1 ? '' : 's'}',
              ),
              const SizedBox(height: AppSpacing.xs),
              const Divider(color: AppColors.sand, height: 1),
              const SizedBox(height: AppSpacing.xs),
              Text(
                description.length > 120
                    ? '${description.substring(0, 120)}...'
                    : description,
                style: const TextStyle(
                  fontSize: 13,
                  color: AppColors.mist,
                  height: 1.4,
                ),
              ),
            ],
          ),
        ),

        const SizedBox(height: AppSpacing.lg),

        // Desired resolution
        const Text(
          'Desired resolution',
          style: TextStyle(
            fontFamily: 'Sora',
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: AppColors.navy,
          ),
        ),
        const SizedBox(height: AppSpacing.sm),
        ...List.generate(_DisputeScreenState._resolutions.length, (i) {
          final r = _DisputeScreenState._resolutions[i];
          final isSelected = resolutionIndex == i;

          return Padding(
            padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
            child: GestureDetector(
              onTap: () {
                HapticFeedback.selectionClick();
                onResolutionChanged(i);
              },
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding: AppSpacing.allMd,
                decoration: BoxDecoration(
                  color: isSelected ? AppColors.cream : Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: isSelected ? AppColors.navy : AppColors.sand,
                    width: 1.5,
                  ),
                ),
                child: Row(
                  children: [
                    Icon(r.icon, color: AppColors.navy, size: 22),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Text(
                        r.title,
                        style: TextStyle(
                          fontFamily: 'Sora',
                          fontSize: 15,
                          fontWeight:
                              isSelected ? FontWeight.w700 : FontWeight.w500,
                          color: AppColors.navy,
                        ),
                      ),
                    ),
                    AnimatedOpacity(
                      duration: const Duration(milliseconds: 200),
                      opacity: isSelected ? 1.0 : 0.0,
                      child: const Icon(
                        Icons.check_circle_rounded,
                        color: AppColors.navy,
                        size: 22,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          );
        }),

        const SizedBox(height: AppSpacing.lg),

        // Important notice
        Container(
          padding: AppSpacing.allMd,
          decoration: BoxDecoration(
            color: AppColors.cream,
            borderRadius: BorderRadius.circular(12),
            border: const BorderDirectional(
              start: BorderSide(color: AppColors.gold, width: 3),
            ),
          ),
          child: const Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Seller has 48h to respond. Our team reviews all disputes within 72h.',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: AppColors.navy,
                  height: 1.5,
                ),
              ),
              SizedBox(height: AppSpacing.xs),
              Text(
                'لدى البائع ٤٨ ساعة للرد. يراجع فريقنا جميع النزاعات خلال ٧٢ ساعة.',
                style: TextStyle(
                  fontSize: 13,
                  color: AppColors.mist,
                  height: 1.5,
                ),
                textDirection: TextDirection.rtl,
              ),
            ],
          ),
        ),

        const SizedBox(height: AppSpacing.xl),
      ],
    );
  }
}

class _SummaryRow extends StatelessWidget {
  const _SummaryRow({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(
          label,
          style: const TextStyle(fontSize: 13, color: AppColors.mist),
        ),
        Text(
          value,
          style: const TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: AppColors.navy,
          ),
        ),
      ],
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Shared widgets
// ══════════════════════════════════════════════════════════════════

/// 3-step progress bar below the AppBar.
class _ProgressBar extends StatelessWidget implements PreferredSizeWidget {
  const _ProgressBar({required this.step, required this.totalSteps});

  final int step;
  final int totalSteps;

  @override
  Size get preferredSize => const Size.fromHeight(4);

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 4,
      child: LayoutBuilder(
        builder: (_, constraints) {
          final fraction = (step + 1) / totalSteps;
          return Stack(
            children: [
              // Track
              Container(
                width: double.infinity,
                color: AppColors.cream,
              ),
              // Fill
              AnimatedContainer(
                duration: const Duration(milliseconds: 300),
                curve: Curves.easeOutCubic,
                width: constraints.maxWidth * fraction,
                color: AppColors.navy,
              ),
            ],
          );
        },
      ),
    );
  }
}

/// Bottom CTA button area.
class _BottomCta extends StatelessWidget {
  const _BottomCta({
    required this.step,
    required this.canContinue,
    required this.submitting,
    this.ctaScale,
    this.onTap,
  });

  final int step;
  final bool canContinue;
  final bool submitting;
  final Animation<double>? ctaScale;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final bottomPad = MediaQuery.of(context).viewPadding.bottom;
    final isSubmit = step == 2;

    Widget button = SizedBox(
      width: double.infinity,
      height: 52,
      child: ElevatedButton(
        onPressed: canContinue && !submitting ? onTap : null,
        style: ElevatedButton.styleFrom(
          backgroundColor: isSubmit ? AppColors.ember : AppColors.navy,
          foregroundColor: Colors.white,
          disabledBackgroundColor: AppColors.sand,
          disabledForegroundColor: AppColors.mist,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        child: submitting
            ? const SizedBox(
                width: 24,
                height: 24,
                child: CircularProgressIndicator(
                  strokeWidth: 2.5,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : Text(
                isSubmit ? 'Submit dispute · تقديم النزاع' : 'Continue →',
                style: const TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
      ),
    );

    // ScaleIn on step 0 when first reason selected
    if (ctaScale != null) {
      button = ScaleTransition(scale: ctaScale!, child: button);
    }

    return Container(
      padding: EdgeInsetsDirectional.only(
        start: 20,
        end: 20,
        top: AppSpacing.sm,
        bottom: bottomPad + AppSpacing.sm,
      ),
      decoration: const BoxDecoration(
        color: AppColors.cream,
        border: Border(
          top: BorderSide(color: AppColors.sand, width: 1),
        ),
      ),
      child: button,
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Painters & models
// ══════════════════════════════════════════════════════════════════

class _DashedBorderPainter extends CustomPainter {
  _DashedBorderPainter({
    required this.color,
    required this.strokeWidth,
    required this.radius,
  });

  final Color color;
  final double strokeWidth;
  final double radius;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = strokeWidth
      ..style = PaintingStyle.stroke;

    final path = Path()
      ..addRRect(RRect.fromRectAndRadius(
        Offset.zero & size,
        Radius.circular(radius),
      ));

    const dashWidth = 8.0;
    const dashGap = 5.0;
    for (final metric in path.computeMetrics()) {
      var distance = 0.0;
      while (distance < metric.length) {
        final end = (distance + dashWidth).clamp(0.0, metric.length);
        canvas.drawPath(metric.extractPath(distance, end), paint);
        distance += dashWidth + dashGap;
      }
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

class _CheckPainter extends CustomPainter {
  _CheckPainter({
    required this.progress,
    required this.color,
    required this.strokeWidth,
  });

  final double progress;
  final Color color;
  final double strokeWidth;

  @override
  void paint(Canvas canvas, Size size) {
    if (progress <= 0) return;

    final paint = Paint()
      ..color = color
      ..strokeWidth = strokeWidth
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;

    final cx = size.width / 2;
    final cy = size.height / 2;
    final s = size.width * 0.28;

    final path = Path()
      ..moveTo(cx - s * 0.6, cy)
      ..lineTo(cx - s * 0.1, cy + s * 0.5)
      ..lineTo(cx + s * 0.7, cy - s * 0.4);

    for (final metric in path.computeMetrics()) {
      canvas.drawPath(
        metric.extractPath(0, metric.length * progress),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(_CheckPainter old) => old.progress != progress;
}

/// Photo evidence with pre-computed SHA-256 hash.
class _EvidencePhoto {
  const _EvidencePhoto({required this.file, required this.hash});

  final XFile file;
  final String hash;
}
