import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Full dispute flow: reason selector → photo evidence upload → submit.
///
/// SDD §7.2:
/// - Reason selector (dropdown)
/// - Photo evidence: camera + gallery, max 10, 5MB each
/// - SHA-256 hash computed client-side before upload (done in provider)
/// - Minimum 1 photo validation
class DisputeFlow extends StatefulWidget {
  const DisputeFlow({
    super.key,
    required this.onSubmit,
  });

  final void Function(String reason, List<XFile> photos) onSubmit;

  /// Show dispute flow as a full-screen modal sheet.
  static Future<void> show({
    required BuildContext context,
    required void Function(String reason, List<XFile> photos) onSubmit,
  }) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => DraggableScrollableSheet(
        initialChildSize: 0.85,
        maxChildSize: 0.95,
        minChildSize: 0.5,
        builder: (_, controller) => _DisputeFlowContent(
          onSubmit: onSubmit,
          scrollController: controller,
        ),
      ),
    );
  }

  @override
  State<DisputeFlow> createState() => _DisputeFlowState();
}

class _DisputeFlowState extends State<DisputeFlow> {
  @override
  Widget build(BuildContext context) {
    return _DisputeFlowContent(onSubmit: widget.onSubmit);
  }
}

class _DisputeFlowContent extends StatefulWidget {
  const _DisputeFlowContent({
    required this.onSubmit,
    this.scrollController,
  });

  final void Function(String reason, List<XFile> photos) onSubmit;
  final ScrollController? scrollController;

  @override
  State<_DisputeFlowContent> createState() => _DisputeFlowContentState();
}

class _DisputeFlowContentState extends State<_DisputeFlowContent> {
  String? _selectedReason;
  final List<XFile> _photos = [];
  final _picker = ImagePicker();
  bool _submitting = false;

  static const _maxPhotos = 10;
  static const _maxSizeBytes = 5 * 1024 * 1024; // 5MB

  static const _reasons = [
    'المنتج لا يطابق الوصف',
    'المنتج تالف',
    'المنتج مفقود / لم يصل',
    'منتج مختلف تماماً',
    'قطع ناقصة أو ملحقات مفقودة',
    'أخرى',
  ];

  bool get _canSubmit =>
      _selectedReason != null && _photos.isNotEmpty && !_submitting;

  Future<void> _pickFromCamera() async {
    if (_photos.length >= _maxPhotos) {
      _showMaxPhotosWarning();
      return;
    }
    final photo = await _picker.pickImage(
      source: ImageSource.camera,
      maxWidth: 1920,
      maxHeight: 1920,
      imageQuality: 85,
    );
    if (photo != null) await _addPhoto(photo);
  }

  Future<void> _pickFromGallery() async {
    final remaining = _maxPhotos - _photos.length;
    if (remaining <= 0) {
      _showMaxPhotosWarning();
      return;
    }
    final photos = await _picker.pickMultiImage(
      maxWidth: 1920,
      maxHeight: 1920,
      imageQuality: 85,
    );
    for (final photo in photos.take(remaining)) {
      await _addPhoto(photo);
    }
  }

  Future<void> _addPhoto(XFile photo) async {
    final size = await photo.length();
    if (size > _maxSizeBytes) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('حجم الصورة يتجاوز 5 ميغابايت'),
          backgroundColor: AppColors.ember,
        ),
      );
      return;
    }
    setState(() => _photos.add(photo));
  }

  void _removePhoto(int index) {
    setState(() => _photos.removeAt(index));
  }

  void _showMaxPhotosWarning() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('الحد الأقصى ١٠ صور'),
        backgroundColor: AppColors.ember,
      ),
    );
  }

  void _submit() {
    if (!_canSubmit) return;
    setState(() => _submitting = true);
    widget.onSubmit(_selectedReason!, _photos);
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      child: Column(
        children: [
          // Drag handle
          Padding(
            padding: const EdgeInsetsDirectional.only(top: AppSpacing.md),
            child: Container(
              width: 40,
              height: 4,
              decoration: BoxDecoration(
                color: AppColors.sand,
                borderRadius: AppSpacing.radiusFull,
              ),
            ),
          ),

          // Scrollable content
          Expanded(
            child: ListView(
              controller: widget.scrollController,
              padding: AppSpacing.allLg,
              children: [
                // Title
                const Text(
                  'الإبلاغ عن مشكلة',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy,
                  ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppSpacing.xs),
                const Text(
                  'الرجاء تحديد سبب المشكلة وإرفاق صور كدليل',
                  style: TextStyle(fontSize: 13, color: AppColors.mist),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: AppSpacing.lg),

                // Reason selector
                const Text(
                  'سبب المشكلة',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.navy,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                ...List.generate(_reasons.length, (i) {
                  final reason = _reasons[i];
                  final isSelected = _selectedReason == reason;
                  return Padding(
                    padding:
                        const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
                    child: InkWell(
                      onTap: () => setState(() => _selectedReason = reason),
                      borderRadius: AppSpacing.radiusMd,
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 150),
                        padding: AppSpacing.allMd,
                        decoration: BoxDecoration(
                          color: isSelected
                              ? AppColors.navy.withOpacity(0.08)
                              : Colors.transparent,
                          border: Border.all(
                            color:
                                isSelected ? AppColors.navy : AppColors.sand,
                            width: isSelected ? 1.5 : 1,
                          ),
                          borderRadius: AppSpacing.radiusMd,
                        ),
                        child: Row(
                          children: [
                            Icon(
                              isSelected
                                  ? Icons.radio_button_checked
                                  : Icons.radio_button_unchecked,
                              color: isSelected
                                  ? AppColors.navy
                                  : AppColors.mist,
                              size: 20,
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: Text(
                                reason,
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: isSelected
                                      ? FontWeight.w500
                                      : FontWeight.w400,
                                  color: isSelected
                                      ? AppColors.navy
                                      : AppColors.ink,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                }),

                const SizedBox(height: AppSpacing.lg),

                // Photo evidence section
                Row(
                  children: [
                    const Text(
                      'صور كدليل',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppColors.navy,
                      ),
                    ),
                    const SizedBox(width: AppSpacing.xs),
                    Text(
                      '(${_photos.length}/$_maxPhotos)',
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.mist,
                      ),
                    ),
                    const Spacer(),
                    if (_photos.isEmpty)
                      const Text(
                        'مطلوب صورة واحدة على الأقل',
                        style: TextStyle(
                          fontSize: 11,
                          color: AppColors.ember,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),

                // Photo grid
                if (_photos.isNotEmpty)
                  Wrap(
                    spacing: AppSpacing.xs,
                    runSpacing: AppSpacing.xs,
                    children: [
                      ..._photos.asMap().entries.map((entry) {
                        return _PhotoTile(
                          file: entry.value,
                          onRemove: () => _removePhoto(entry.key),
                        );
                      }),
                      if (_photos.length < _maxPhotos)
                        _AddPhotoTile(
                          onCamera: _pickFromCamera,
                          onGallery: _pickFromGallery,
                        ),
                    ],
                  )
                else
                  _AddPhotoTile(
                    onCamera: _pickFromCamera,
                    onGallery: _pickFromGallery,
                    large: true,
                  ),

                const SizedBox(height: AppSpacing.xl),
              ],
            ),
          ),

          // Submit button (pinned at bottom)
          Container(
            padding: EdgeInsetsDirectional.only(
              start: AppSpacing.lg,
              end: AppSpacing.lg,
              top: AppSpacing.sm,
              bottom:
                  MediaQuery.of(context).viewPadding.bottom + AppSpacing.sm,
            ),
            decoration: const BoxDecoration(
              color: Colors.white,
              border: Border(
                top: BorderSide(color: AppColors.sand, width: 1),
              ),
            ),
            child: SizedBox(
              width: double.infinity,
              height: 52,
              child: ElevatedButton(
                onPressed: _canSubmit ? _submit : null,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.ember,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: AppColors.sand,
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.radiusMd,
                  ),
                ),
                child: _submitting
                    ? const SizedBox(
                        width: 24,
                        height: 24,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          valueColor:
                              AlwaysStoppedAnimation<Color>(Colors.white),
                        ),
                      )
                    : const Text(
                        'إرسال البلاغ',
                        style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PhotoTile extends StatelessWidget {
  const _PhotoTile({required this.file, required this.onRemove});

  final XFile file;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        ClipRRect(
          borderRadius: AppSpacing.radiusMd,
          child: Image.file(
            File(file.path),
            width: 80,
            height: 80,
            fit: BoxFit.cover,
          ),
        ),
        PositionedDirectional(
          top: 2,
          end: 2,
          child: GestureDetector(
            onTap: onRemove,
            child: Container(
              width: 22,
              height: 22,
              decoration: const BoxDecoration(
                color: AppColors.ember,
                shape: BoxShape.circle,
              ),
              child: const Icon(Icons.close, color: Colors.white, size: 14),
            ),
          ),
        ),
      ],
    );
  }
}

class _AddPhotoTile extends StatelessWidget {
  const _AddPhotoTile({
    required this.onCamera,
    required this.onGallery,
    this.large = false,
  });

  final VoidCallback onCamera;
  final VoidCallback onGallery;
  final bool large;

  @override
  Widget build(BuildContext context) {
    if (large) {
      return Container(
        height: 120,
        decoration: BoxDecoration(
          border: Border.all(color: AppColors.sand, width: 2),
          borderRadius: AppSpacing.radiusMd,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            _PickerButton(
              icon: Icons.camera_alt_rounded,
              label: 'الكاميرا',
              onTap: onCamera,
            ),
            const SizedBox(width: AppSpacing.xl),
            _PickerButton(
              icon: Icons.photo_library_rounded,
              label: 'المعرض',
              onTap: onGallery,
            ),
          ],
        ),
      );
    }

    return GestureDetector(
      onTap: () => _showPickerOptions(context),
      child: Container(
        width: 80,
        height: 80,
        decoration: BoxDecoration(
          border: Border.all(color: AppColors.sand, width: 2),
          borderRadius: AppSpacing.radiusMd,
        ),
        child: const Icon(Icons.add_a_photo_rounded,
            color: AppColors.mist, size: 24),
      ),
    );
  }

  void _showPickerOptions(BuildContext context) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.camera_alt_rounded),
              title: const Text('الكاميرا'),
              onTap: () {
                Navigator.pop(context);
                onCamera();
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_rounded),
              title: const Text('المعرض'),
              onTap: () {
                Navigator.pop(context);
                onGallery();
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _PickerButton extends StatelessWidget {
  const _PickerButton({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: AppColors.navy.withOpacity(0.08),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: AppColors.navy, size: 24),
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            label,
            style: const TextStyle(fontSize: 12, color: AppColors.navy),
          ),
        ],
      ),
    );
  }
}
