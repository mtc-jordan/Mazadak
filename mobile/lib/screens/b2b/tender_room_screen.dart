import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/core_providers.dart';
import '../../core/theme/animations.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';

// ═══════════════════════════════════════════════════════════════
// B2B Color Tokens — formal, cooler palette
// ═══════════════════════════════════════════════════════════════

const _steel = Color(0xFF2A5F8F);
const _steelLight = Color(0xFF3A7AB5);
const _steelSurface = Color(0xFFEBF1F8);
const _steelDim = Color(0xFF5A88B0);

// ═══════════════════════════════════════════════════════════════
// Models
// ═══════════════════════════════════════════════════════════════

enum TenderAccess { loading, denied, invited }

enum TenderPhase { open, submitted, resultsAnnounced }

enum BidResult { won, lost, pending }

class TenderDocument {
  const TenderDocument({
    required this.name,
    required this.size,
    required this.url,
  });
  final String name;
  final String size;
  final String url;

  factory TenderDocument.fromJson(Map<String, dynamic> json) =>
      TenderDocument(
        name: json['name'] as String,
        size: json['size'] as String? ?? '',
        url: json['url'] as String,
      );
}

class TenderResult {
  const TenderResult({
    required this.rank,
    required this.amount,
    required this.isAwarded,
    required this.isYou,
  });
  final int rank;
  final double amount;
  final bool isAwarded;
  final bool isYou;
}

// ═══════════════════════════════════════════════════════════════
// Provider
// ═══════════════════════════════════════════════════════════════

class TenderRoomState {
  const TenderRoomState({
    this.access = TenderAccess.loading,
    this.phase = TenderPhase.open,
    this.clientName,
    this.clientLogoUrl,
    this.reference,
    this.deadlineIso,
    this.sealedNotice = true,
    this.documents = const [],
    this.submittedAt,
    this.submissionRef,
    this.bidResult = BidResult.pending,
    this.results = const [],
    this.winningAmount,
    this.isSubmitting = false,
  });

  final TenderAccess access;
  final TenderPhase phase;
  final String? clientName;
  final String? clientLogoUrl;
  final String? reference;
  final String? deadlineIso;
  final bool sealedNotice;
  final List<TenderDocument> documents;
  final String? submittedAt;
  final String? submissionRef;
  final BidResult bidResult;
  final List<TenderResult> results;
  final double? winningAmount;
  final bool isSubmitting;

  TenderRoomState copyWith({
    TenderAccess? access,
    TenderPhase? phase,
    String? clientName,
    String? clientLogoUrl,
    String? reference,
    String? deadlineIso,
    bool? sealedNotice,
    List<TenderDocument>? documents,
    String? submittedAt,
    String? submissionRef,
    BidResult? bidResult,
    List<TenderResult>? results,
    double? winningAmount,
    bool? isSubmitting,
  }) =>
      TenderRoomState(
        access: access ?? this.access,
        phase: phase ?? this.phase,
        clientName: clientName ?? this.clientName,
        clientLogoUrl: clientLogoUrl ?? this.clientLogoUrl,
        reference: reference ?? this.reference,
        deadlineIso: deadlineIso ?? this.deadlineIso,
        sealedNotice: sealedNotice ?? this.sealedNotice,
        documents: documents ?? this.documents,
        submittedAt: submittedAt ?? this.submittedAt,
        submissionRef: submissionRef ?? this.submissionRef,
        bidResult: bidResult ?? this.bidResult,
        results: results ?? this.results,
        winningAmount: winningAmount ?? this.winningAmount,
        isSubmitting: isSubmitting ?? this.isSubmitting,
      );
}

final tenderRoomProvider = StateNotifierProvider.autoDispose
    .family<TenderRoomNotifier, TenderRoomState, String>((ref, tenderId) {
  return TenderRoomNotifier(ref, tenderId);
});

class TenderRoomNotifier extends StateNotifier<TenderRoomState> {
  TenderRoomNotifier(this._ref, this._tenderId)
      : super(const TenderRoomState()) {
    _load();
  }

  final Ref _ref;
  final String _tenderId;

  Future<void> _load() async {
    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/tenders/$_tenderId');
      final data = resp.data as Map<String, dynamic>;

      final accessStr = data['access'] as String? ?? 'denied';
      final access = accessStr == 'invited'
          ? TenderAccess.invited
          : TenderAccess.denied;

      if (access == TenderAccess.denied) {
        state = state.copyWith(access: TenderAccess.denied);
        return;
      }

      final phaseStr = data['phase'] as String? ?? 'open';
      final phase = switch (phaseStr) {
        'submitted' => TenderPhase.submitted,
        'results' => TenderPhase.resultsAnnounced,
        _ => TenderPhase.open,
      };

      final docs = (data['documents'] as List?)
              ?.map((e) =>
                  TenderDocument.fromJson(e as Map<String, dynamic>))
              .toList() ??
          [];

      final resultsRaw = data['results'] as List?;
      final results = resultsRaw
              ?.map((e) => TenderResult(
                    rank: e['rank'] as int,
                    amount: (e['amount'] as num).toDouble(),
                    isAwarded: e['is_awarded'] as bool? ?? false,
                    isYou: e['is_you'] as bool? ?? false,
                  ))
              .toList() ??
          [];

      final bidResultStr = data['bid_result'] as String? ?? 'pending';
      final bidResult = switch (bidResultStr) {
        'won' => BidResult.won,
        'lost' => BidResult.lost,
        _ => BidResult.pending,
      };

      state = state.copyWith(
        access: TenderAccess.invited,
        phase: phase,
        clientName: data['client_name'] as String?,
        clientLogoUrl: data['client_logo_url'] as String?,
        reference: data['reference'] as String?,
        deadlineIso: data['deadline'] as String?,
        documents: docs,
        submittedAt: data['submitted_at'] as String?,
        submissionRef: data['submission_ref'] as String?,
        bidResult: bidResult,
        results: results,
        winningAmount: (data['winning_amount'] as num?)?.toDouble(),
      );
    } catch (_) {
      state = state.copyWith(access: TenderAccess.denied);
    }
  }

  Future<bool> submitBid({
    required double amount,
    required String notes,
    required int validityDays,
    required List<String> attachmentPaths,
  }) async {
    state = state.copyWith(isSubmitting: true);
    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.post('/tenders/$_tenderId/bids', data: {
        'amount': amount,
        'notes': notes,
        'validity_days': validityDays,
        'attachment_paths': attachmentPaths,
      });
      final data = resp.data as Map<String, dynamic>;
      state = state.copyWith(
        isSubmitting: false,
        phase: TenderPhase.submitted,
        submittedAt: data['submitted_at'] as String?,
        submissionRef: data['submission_ref'] as String?,
      );
      return true;
    } catch (_) {
      state = state.copyWith(isSubmitting: false);
      return false;
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// Screen
// ═══════════════════════════════════════════════════════════════

class TenderRoomScreen extends ConsumerStatefulWidget {
  const TenderRoomScreen({super.key, required this.tenderId});
  final String tenderId;

  @override
  ConsumerState<TenderRoomScreen> createState() => _TenderRoomScreenState();
}

class _TenderRoomScreenState extends ConsumerState<TenderRoomScreen> {
  final _amountController = TextEditingController();
  final _notesController = TextEditingController();
  int _validityDays = 30;
  final List<String> _attachments = [];

  Timer? _countdownTimer;
  Duration _remaining = Duration.zero;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _startCountdown();
    });
  }

  void _startCountdown() {
    _countdownTimer?.cancel();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      final s = ref.read(tenderRoomProvider(widget.tenderId));
      if (s.deadlineIso == null) return;
      final deadline = DateTime.tryParse(s.deadlineIso!);
      if (deadline == null) return;
      final diff = deadline.toUtc().difference(DateTime.now().toUtc());
      if (mounted) {
        setState(() {
          _remaining = diff.isNegative ? Duration.zero : diff;
        });
      }
    });
  }

  @override
  void dispose() {
    _amountController.dispose();
    _notesController.dispose();
    _countdownTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(tenderRoomProvider(widget.tenderId));

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        title: const Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.lock_rounded, size: 16, color: Colors.white54),
            SizedBox(width: AppSpacing.xs),
            Text(
              'Tender Room · غرفة المناقصة',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                fontFamily: 'Sora',
              ),
            ),
          ],
        ),
      ),
      body: switch (state.access) {
        TenderAccess.loading => const Center(
            child: CircularProgressIndicator(color: AppColors.navy),
          ),
        TenderAccess.denied => const _AccessGate(),
        TenderAccess.invited => _buildInvitedBody(state),
      },
    );
  }

  Widget _buildInvitedBody(TenderRoomState state) {
    return ListView(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      children: [
        // ── Room Header ────────────────────────────────────────
        _RoomHeader(
          state: state,
          remaining: _remaining,
        ),
        const SizedBox(height: AppSpacing.md),

        // ── Phase-specific content ─────────────────────────────
        if (state.phase == TenderPhase.open) ...[
          _DocumentsSection(documents: state.documents),
          const SizedBox(height: AppSpacing.md),
          _BidForm(
            amountController: _amountController,
            notesController: _notesController,
            validityDays: _validityDays,
            attachments: _attachments,
            isSubmitting: state.isSubmitting,
            onValidityChanged: (v) => setState(() => _validityDays = v),
            onPickFile: _pickFile,
            onRemoveFile: (i) => setState(() => _attachments.removeAt(i)),
            onSubmit: () => _confirmSubmit(context),
          ),
        ] else if (state.phase == TenderPhase.submitted) ...[
          _SubmittedState(
            submittedAt: state.submittedAt,
            submissionRef: state.submissionRef,
          ),
          const SizedBox(height: AppSpacing.md),
          _DocumentsSection(documents: state.documents),
        ] else if (state.phase == TenderPhase.resultsAnnounced) ...[
          _ResultsBanner(bidResult: state.bidResult),
          const SizedBox(height: AppSpacing.md),
          _ResultsTable(
            results: state.results,
            winningAmount: state.winningAmount,
          ),
        ],

        const SizedBox(height: AppSpacing.xxl),
      ],
    );
  }

  Future<void> _pickFile() async {
    try {
      final picker = ImagePicker();
      // Using pickMedia as a proxy; in production use file_picker for PDF/Excel
      final result = await picker.pickMedia();
      if (result != null && mounted) {
        setState(() => _attachments.add(result.name));
      }
    } catch (_) {}
  }

  Future<void> _confirmSubmit(BuildContext context) async {
    final amountText = _amountController.text.trim();
    if (amountText.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter a bid amount')),
      );
      return;
    }

    final amount = double.tryParse(amountText);
    if (amount == null || amount <= 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Invalid amount')),
      );
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        title: const Row(
          children: [
            Icon(Icons.warning_amber_rounded, color: AppColors.ember, size: 22),
            SizedBox(width: AppSpacing.xs),
            Expanded(
              child: Text(
                'Confirm Submission',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
              ),
            ),
          ],
        ),
        content: Text(
          'Once submitted, bids cannot be edited.\n\n'
          'Bid amount: ${ArabicNumerals.formatCurrencyEn(amount, 'JOD')}\n'
          'Validity: $_validityDays days\n\n'
          'Confirm submission?',
          style: const TextStyle(fontSize: 13, height: 1.5),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.navy,
              foregroundColor: Colors.white,
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.radiusSm,
              ),
            ),
            child: const Text('Submit Bid'),
          ),
        ],
      ),
    );

    if (confirmed == true && mounted) {
      HapticFeedback.heavyImpact();
      final ok = await ref
          .read(tenderRoomProvider(widget.tenderId).notifier)
          .submitBid(
            amount: amount,
            notes: _notesController.text.trim(),
            validityDays: _validityDays,
            attachmentPaths: _attachments,
          );
      if (ok && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Bid submitted successfully'),
            backgroundColor: AppColors.emerald,
          ),
        );
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// Access Gate
// ═══════════════════════════════════════════════════════════════

class _AccessGate extends StatelessWidget {
  const _AccessGate();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsetsDirectional.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Padlock illustration
            SizedBox(
              width: 96,
              height: 96,
              child: CustomPaint(painter: _PadlockPainter()),
            ),
            const SizedBox(height: AppSpacing.lg),
            const Text(
              'This room is invite-only',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.navy,
                fontFamily: 'Sora',
              ),
            ),
            const SizedBox(height: AppSpacing.xxs),
            const Text(
              'هذه الغرفة بدعوة فقط',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w600,
                color: AppColors.mist,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            const Text(
              'Contact your procurement manager\nor MZADAK B2B team',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.mist,
                height: 1.5,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            OutlinedButton.icon(
              onPressed: () {
                HapticFeedback.lightImpact();
                launchUrl(
                  Uri.parse('mailto:b2b@mzadak.com?subject=Tender%20Access%20Request'),
                );
              },
              icon: const Icon(Icons.mail_outline_rounded, size: 18),
              label: const Text('Request access'),
              style: OutlinedButton.styleFrom(
                foregroundColor: _steel,
                side: const BorderSide(color: _steel, width: 1.5),
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusMd,
                ),
                padding: const EdgeInsetsDirectional.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.sm,
                ),
                textStyle: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  fontFamily: 'Sora',
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Padlock CustomPainter
// ═══════════════════════════════════════════════════════════════

class _PadlockPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;

    final paint = Paint()
      ..color = AppColors.navy
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3.5
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    // Shackle (top arc)
    final shackleRect = Rect.fromLTWH(w * 0.26, h * 0.08, w * 0.48, h * 0.42);
    canvas.drawArc(shackleRect, math.pi, math.pi, false, paint);

    // Shackle legs
    canvas.drawLine(
      Offset(w * 0.26, h * 0.29),
      Offset(w * 0.26, h * 0.42),
      paint,
    );
    canvas.drawLine(
      Offset(w * 0.74, h * 0.29),
      Offset(w * 0.74, h * 0.42),
      paint,
    );

    // Body (rounded rectangle)
    final bodyPaint = Paint()
      ..color = AppColors.navy
      ..style = PaintingStyle.fill;

    final bodyRect = RRect.fromRectAndRadius(
      Rect.fromLTWH(w * 0.18, h * 0.40, w * 0.64, h * 0.48),
      const Radius.circular(8),
    );
    canvas.drawRRect(bodyRect, bodyPaint);

    // Keyhole
    final keyholePaint = Paint()
      ..color = AppColors.cream
      ..style = PaintingStyle.fill;

    final keyCx = w * 0.5;
    final keyCy = h * 0.57;
    canvas.drawCircle(Offset(keyCx, keyCy), w * 0.06, keyholePaint);

    // Keyhole slot
    final slotPath = Path()
      ..moveTo(keyCx - w * 0.025, keyCy + w * 0.04)
      ..lineTo(keyCx + w * 0.025, keyCy + w * 0.04)
      ..lineTo(keyCx + w * 0.015, keyCy + w * 0.13)
      ..lineTo(keyCx - w * 0.015, keyCy + w * 0.13)
      ..close();
    canvas.drawPath(slotPath, keyholePaint);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

// ═══════════════════════════════════════════════════════════════
// Room Header
// ═══════════════════════════════════════════════════════════════

class _RoomHeader extends StatelessWidget {
  const _RoomHeader({required this.state, required this.remaining});
  final TenderRoomState state;
  final Duration remaining;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              // Client logo
              Container(
                width: 56,
                height: 56,
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.sand, width: 1.5),
                ),
                child: state.clientLogoUrl != null
                    ? ClipRRect(
                        borderRadius: BorderRadius.circular(11),
                        child: Image.network(
                          state.clientLogoUrl!,
                          fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) =>
                              _clientInitial(state.clientName),
                        ),
                      )
                    : _clientInitial(state.clientName),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      state.clientName ?? 'Client',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                        fontFamily: 'Sora',
                      ),
                    ),
                    if (state.reference != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        state.reference!,
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                          color: AppColors.mist,
                          fontFamily: 'Sora',
                          letterSpacing: 0.3,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),

          // Deadline timer
          if (remaining > Duration.zero) ...[
            const SizedBox(height: AppSpacing.sm),
            Container(
              padding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm,
                vertical: AppSpacing.xs,
              ),
              decoration: BoxDecoration(
                color: AppColors.ember.withOpacity(0.08),
                borderRadius: AppSpacing.radiusSm,
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.timer_rounded, size: 14, color: AppColors.ember),
                  const SizedBox(width: AppSpacing.xxs),
                  Text(
                    'Deadline: ${_formatDuration(remaining)}',
                    style: const TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ember,
                      fontFamily: 'Sora',
                    ),
                  ),
                ],
              ),
            ),
          ],

          // Sealed bid notice
          if (state.sealedNotice && state.phase == TenderPhase.open) ...[
            const SizedBox(height: AppSpacing.sm),
            Container(
              width: double.infinity,
              padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF8E1),
                borderRadius: AppSpacing.radiusSm,
                border: Border.all(
                  color: const Color(0xFFFFE082),
                  width: 1,
                ),
              ),
              child: const Row(
                children: [
                  Icon(Icons.visibility_off_rounded, size: 16, color: Color(0xFF9A6420)),
                  SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Your bid is private until deadline',
                          style: TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w600,
                            color: Color(0xFF9A6420),
                          ),
                        ),
                        SizedBox(height: 1),
                        Text(
                          'مزايدتك سرية حتى انتهاء المهلة',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w500,
                            color: AppColors.mist,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _clientInitial(String? name) {
    return Center(
      child: Text(
        name?.substring(0, 1).toUpperCase() ?? 'B',
        style: const TextStyle(
          fontSize: 22,
          fontWeight: FontWeight.w800,
          color: _steel,
          fontFamily: 'Sora',
        ),
      ),
    );
  }

  String _formatDuration(Duration d) {
    final days = d.inDays;
    final hours = d.inHours.remainder(24);
    final minutes = d.inMinutes.remainder(60);
    final seconds = d.inSeconds.remainder(60);

    if (days > 0) {
      return '${days}d ${_p(hours)}:${_p(minutes)}:${_p(seconds)}';
    }
    return '${_p(hours)}:${_p(minutes)}:${_p(seconds)}';
  }

  String _p(int n) => n.toString().padLeft(2, '0');
}

// ═══════════════════════════════════════════════════════════════
// Documents Section
// ═══════════════════════════════════════════════════════════════

class _DocumentsSection extends StatelessWidget {
  const _DocumentsSection({required this.documents});
  final List<TenderDocument> documents;

  @override
  Widget build(BuildContext context) {
    if (documents.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.folder_outlined, size: 18, color: _steel),
              SizedBox(width: AppSpacing.xs),
              Text(
                'Tender Documents · مستندات المناقصة',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          ...documents.map((doc) => _DocumentRow(document: doc)),
        ],
      ),
    );
  }
}

class _DocumentRow extends StatelessWidget {
  const _DocumentRow({required this.document});
  final TenderDocument document;

  IconData get _icon {
    final ext = document.name.split('.').last.toLowerCase();
    return switch (ext) {
      'pdf' => Icons.picture_as_pdf_rounded,
      'xlsx' || 'xls' => Icons.table_chart_rounded,
      'docx' || 'doc' => Icons.description_rounded,
      _ => Icons.insert_drive_file_rounded,
    };
  }

  Color get _iconColor {
    final ext = document.name.split('.').last.toLowerCase();
    return switch (ext) {
      'pdf' => AppColors.ember,
      'xlsx' || 'xls' => AppColors.emerald,
      _ => _steel,
    };
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xs),
      child: Material(
        color: _steelSurface,
        borderRadius: AppSpacing.radiusSm,
        child: InkWell(
          onTap: () {
            HapticFeedback.lightImpact();
            launchUrl(Uri.parse(document.url), mode: LaunchMode.externalApplication);
          },
          borderRadius: AppSpacing.radiusSm,
          child: Padding(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xs + 2,
            ),
            child: Row(
              children: [
                Icon(_icon, size: 22, color: _iconColor),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        document.name,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink,
                        ),
                      ),
                      if (document.size.isNotEmpty)
                        Text(
                          document.size,
                          style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.w500,
                            color: AppColors.mist,
                          ),
                        ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.download_rounded,
                  size: 20,
                  color: _steel,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Bid Submission Form
// ═══════════════════════════════════════════════════════════════

class _BidForm extends StatelessWidget {
  const _BidForm({
    required this.amountController,
    required this.notesController,
    required this.validityDays,
    required this.attachments,
    required this.isSubmitting,
    required this.onValidityChanged,
    required this.onPickFile,
    required this.onRemoveFile,
    required this.onSubmit,
  });

  final TextEditingController amountController;
  final TextEditingController notesController;
  final int validityDays;
  final List<String> attachments;
  final bool isSubmitting;
  final ValueChanged<int> onValidityChanged;
  final VoidCallback onPickFile;
  final ValueChanged<int> onRemoveFile;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.edit_note_rounded, size: 18, color: _steel),
              SizedBox(width: AppSpacing.xs),
              Text(
                'Bid Submission · تقديم العرض',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),

          // Amount field
          const Text(
            'Your bid (JOD) · عرضك (دينار)',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.mist,
            ),
          ),
          const SizedBox(height: AppSpacing.xxs),
          TextField(
            controller: amountController,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            textDirection: TextDirection.ltr,
            style: const TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: AppColors.navy,
              fontFamily: 'Sora',
            ),
            decoration: InputDecoration(
              hintText: '0.000',
              hintStyle: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w800,
                color: AppColors.mist.withOpacity(0.3),
                fontFamily: 'Sora',
              ),
              suffixText: 'JOD',
              suffixStyle: const TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: _steel,
                fontFamily: 'Sora',
              ),
              contentPadding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm,
                vertical: AppSpacing.sm,
              ),
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
                borderSide: const BorderSide(color: _steel, width: 1.5),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Notes field
          const Text(
            'Notes / Technical proposal · ملاحظات',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.mist,
            ),
          ),
          const SizedBox(height: AppSpacing.xxs),
          TextField(
            controller: notesController,
            maxLines: 5,
            minLines: 5,
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w500,
              color: AppColors.ink,
            ),
            decoration: InputDecoration(
              hintText: 'Enter technical proposal or notes...',
              hintStyle: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.mist.withOpacity(0.5),
              ),
              contentPadding: const EdgeInsetsDirectional.all(AppSpacing.sm),
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
                borderSide: const BorderSide(color: _steel, width: 1.5),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Validity dropdown
          const Text(
            'Validity period · مدة الصلاحية',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.mist,
            ),
          ),
          const SizedBox(height: AppSpacing.xxs),
          Container(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
            ),
            decoration: BoxDecoration(
              borderRadius: AppSpacing.radiusMd,
              border: Border.all(color: AppColors.sand),
            ),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<int>(
                value: validityDays,
                isExpanded: true,
                icon: const Icon(Icons.keyboard_arrow_down_rounded, color: _steel),
                style: const TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: AppColors.ink,
                  fontFamily: 'Sora',
                ),
                items: const [
                  DropdownMenuItem(value: 30, child: Text('30 days')),
                  DropdownMenuItem(value: 60, child: Text('60 days')),
                  DropdownMenuItem(value: 90, child: Text('90 days')),
                ],
                onChanged: (v) {
                  if (v != null) onValidityChanged(v);
                },
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),

          // Attachments
          const Text(
            'Supporting documents · مستندات داعمة',
            style: TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.mist,
            ),
          ),
          const SizedBox(height: AppSpacing.xs),

          if (attachments.isNotEmpty) ...[
            Wrap(
              spacing: AppSpacing.xs,
              runSpacing: AppSpacing.xs,
              children: List.generate(attachments.length, (i) {
                return Chip(
                  label: Text(
                    attachments[i],
                    style: const TextStyle(fontSize: 11, color: AppColors.ink),
                  ),
                  deleteIcon:
                      const Icon(Icons.close_rounded, size: 14, color: AppColors.mist),
                  onDeleted: () => onRemoveFile(i),
                  backgroundColor: _steelSurface,
                  side: BorderSide.none,
                  shape: RoundedRectangleBorder(
                    borderRadius: AppSpacing.radiusSm,
                  ),
                );
              }),
            ),
            const SizedBox(height: AppSpacing.xs),
          ],

          OutlinedButton.icon(
            onPressed: onPickFile,
            icon: const Icon(Icons.attach_file_rounded, size: 16),
            label: const Text('Attach PDF / Excel'),
            style: OutlinedButton.styleFrom(
              foregroundColor: _steel,
              side: const BorderSide(color: _steel),
              shape: RoundedRectangleBorder(
                borderRadius: AppSpacing.radiusSm,
              ),
              textStyle: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
                fontFamily: 'Sora',
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.lg),

          // Submit button
          SizedBox(
            width: double.infinity,
            height: 52,
            child: ElevatedButton(
              onPressed: isSubmitting ? null : onSubmit,
              style: ElevatedButton.styleFrom(
                backgroundColor: AppColors.navy,
                foregroundColor: Colors.white,
                disabledBackgroundColor: AppColors.navy.withOpacity(0.5),
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: AppSpacing.radiusMd,
                ),
              ),
              child: isSubmitting
                  ? const SizedBox(
                      width: 22,
                      height: 22,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.lock_rounded, size: 18),
                        SizedBox(width: AppSpacing.xs),
                        Text(
                          'Submit sealed bid · تقديم العرض',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w700,
                            fontFamily: 'Sora',
                          ),
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

// ═══════════════════════════════════════════════════════════════
// Post-Submission State
// ═══════════════════════════════════════════════════════════════

class _SubmittedState extends StatelessWidget {
  const _SubmittedState({this.submittedAt, this.submissionRef});
  final String? submittedAt;
  final String? submissionRef;

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 600),
      curve: Curves.elasticOut,
      builder: (_, value, child) =>
          Transform.scale(scale: value.clamp(0.0, 1.2), child: child),
      child: Container(
        padding: const EdgeInsetsDirectional.all(AppSpacing.lg),
        decoration: BoxDecoration(
          color: AppColors.emerald.withOpacity(0.06),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: AppColors.emerald.withOpacity(0.2),
            width: 1,
          ),
        ),
        child: Column(
          children: [
            const Icon(
              Icons.check_circle_rounded,
              color: AppColors.emerald,
              size: 48,
            ),
            const SizedBox(height: AppSpacing.sm),
            const Text(
              'Bid submitted \u2713',
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: AppColors.emerald,
                fontFamily: 'Sora',
              ),
            ),
            const SizedBox(height: AppSpacing.xxs),
            const Text(
              'تم تقديم العرض بنجاح',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: AppColors.mist,
              ),
            ),
            const SizedBox(height: AppSpacing.md),

            if (submissionRef != null)
              _InfoRow(label: 'Reference', value: submissionRef!),
            if (submittedAt != null)
              _InfoRow(label: 'Submitted', value: submittedAt!),

            const SizedBox(height: AppSpacing.sm),
            const Text(
              'You\'ll be notified when results are announced',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w500,
                color: AppColors.mist,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.label, required this.value});
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.xxs),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            '$label: ',
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w500,
              color: AppColors.mist,
            ),
          ),
          Text(
            value,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: AppColors.ink,
              fontFamily: 'Sora',
            ),
          ),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Results View
// ═══════════════════════════════════════════════════════════════

class _ResultsBanner extends StatelessWidget {
  const _ResultsBanner({required this.bidResult});
  final BidResult bidResult;

  @override
  Widget build(BuildContext context) {
    if (bidResult == BidResult.won) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsetsDirectional.all(AppSpacing.md),
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [Color(0xFF9A6420), Color(0xFFBB8930)],
          ),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.emoji_events_rounded, color: Colors.white, size: 24),
            SizedBox(width: AppSpacing.xs),
            Text(
              'You won! Contract awarded \u2713',
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                fontFamily: 'Sora',
              ),
            ),
          ],
        ),
      );
    }

    if (bidResult == BidResult.lost) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsetsDirectional.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.sand,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.sand),
        ),
        child: const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(Icons.info_outline_rounded, color: AppColors.mist, size: 20),
            SizedBox(width: AppSpacing.xs),
            Text(
              'Contract awarded to another bidder',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: AppColors.mist,
              ),
            ),
          ],
        ),
      );
    }

    return const SizedBox.shrink();
  }
}

class _ResultsTable extends StatelessWidget {
  const _ResultsTable({required this.results, this.winningAmount});
  final List<TenderResult> results;
  final double? winningAmount;

  @override
  Widget build(BuildContext context) {
    if (results.isEmpty) return const SizedBox.shrink();

    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.leaderboard_rounded, size: 18, color: _steel),
              SizedBox(width: AppSpacing.xs),
              Text(
                'Results · النتائج',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),

          // Table header
          Container(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xs,
            ),
            decoration: BoxDecoration(
              color: _steelSurface,
              borderRadius: AppSpacing.radiusSm,
            ),
            child: const Row(
              children: [
                SizedBox(
                  width: 50,
                  child: Text(
                    'Rank',
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      color: AppColors.mist,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
                Expanded(
                  child: Text(
                    'Bid Amount',
                    style: TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.w700,
                      color: AppColors.mist,
                      letterSpacing: 0.5,
                    ),
                  ),
                ),
                Text(
                  'Status',
                  style: TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w700,
                    color: AppColors.mist,
                    letterSpacing: 0.5,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.xxs),

          // Table rows
          ...results.map((r) => _ResultRow(result: r)),

          // Winning amount note (per government tender rules)
          if (winningAmount != null) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(
              'Winning bid: ${ArabicNumerals.formatCurrencyEn(winningAmount!, 'JOD')}',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: AppColors.mist,
                fontStyle: FontStyle.italic,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _ResultRow extends StatelessWidget {
  const _ResultRow({required this.result});
  final TenderResult result;

  @override
  Widget build(BuildContext context) {
    final isHighlighted = result.isYou || result.isAwarded;

    return Container(
      margin: const EdgeInsetsDirectional.only(bottom: 2),
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.sm,
        vertical: AppSpacing.xs + 2,
      ),
      decoration: BoxDecoration(
        color: result.isYou
            ? _steelSurface
            : result.isAwarded
                ? AppColors.emerald.withOpacity(0.06)
                : Colors.transparent,
        borderRadius: AppSpacing.radiusSm,
      ),
      child: Row(
        children: [
          SizedBox(
            width: 50,
            child: Text(
              '#${result.rank}',
              style: TextStyle(
                fontSize: 13,
                fontWeight: isHighlighted ? FontWeight.w700 : FontWeight.w500,
                color: isHighlighted ? AppColors.navy : AppColors.mist,
                fontFamily: 'Sora',
              ),
            ),
          ),
          Expanded(
            child: Row(
              children: [
                Text(
                  ArabicNumerals.formatCurrencyEn(result.amount, 'JOD'),
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w700,
                    color: isHighlighted ? AppColors.navy : AppColors.ink,
                    fontFamily: 'Sora',
                  ),
                ),
                if (result.isYou) ...[
                  const SizedBox(width: AppSpacing.xxs),
                  Container(
                    padding: const EdgeInsetsDirectional.symmetric(
                      horizontal: 5,
                      vertical: 1,
                    ),
                    decoration: BoxDecoration(
                      color: _steel,
                      borderRadius: AppSpacing.radiusSm,
                    ),
                    child: const Text(
                      'YOU',
                      style: TextStyle(
                        fontSize: 8,
                        fontWeight: FontWeight.w800,
                        color: Colors.white,
                        fontFamily: 'Sora',
                        letterSpacing: 0.5,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (result.isAwarded)
            Container(
              padding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.xs,
                vertical: 3,
              ),
              decoration: BoxDecoration(
                color: AppColors.emerald,
                borderRadius: AppSpacing.radiusSm,
              ),
              child: const Text(
                'Awarded',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: Colors.white,
                  fontFamily: 'Sora',
                ),
              ),
            )
          else
            const Text(
              '—',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppColors.mist,
              ),
            ),
        ],
      ),
    );
  }
}
