import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/providers/escrow_provider.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import 'widgets/dispute_flow.dart';
import 'widgets/escrow_actions.dart';
import 'widgets/progress_tracker.dart';
import 'widgets/shipping_form.dart';

/// EscrowOrderScreen — full order lifecycle view.
///
/// SDD §7.2: Composes progress tracker, live state polling,
/// state-based action buttons, and dispute flow.
class EscrowOrderScreen extends ConsumerWidget {
  const EscrowOrderScreen({
    super.key,
    required this.escrowId,
  });

  final String escrowId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final escrow = ref.watch(escrowProvider(escrowId));
    final auth = ref.watch(authProvider);
    final isSeller = auth.userId == escrow.sellerId;

    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            // ── App bar ─────────────────────────────────────────────
            _buildAppBar(context, escrow),

            // ── Scrollable content ──────────────────────────────────
            Expanded(
              child: RefreshIndicator(
                onRefresh: () =>
                    ref.read(escrowProvider(escrowId).notifier).loadEscrow(),
                child: ListView(
                  padding: const EdgeInsetsDirectional.only(
                    top: AppSpacing.md,
                    bottom: AppSpacing.xxxl,
                  ),
                  children: [
                    // ── Progress tracker ────────────────────────────
                    EscrowProgressTracker(currentStep: escrow.stepIndex),
                    const SizedBox(height: AppSpacing.xl),

                    // ── Order summary card ──────────────────────────
                    _OrderSummaryCard(escrow: escrow),
                    const SizedBox(height: AppSpacing.md),

                    // ── Tracking info ───────────────────────────────
                    if (escrow.trackingNumber != null)
                      _TrackingCard(escrow: escrow),

                    // ── Deadline info ───────────────────────────────
                    _DeadlineCard(escrow: escrow),
                    const SizedBox(height: AppSpacing.md),

                    // ── Action buttons ──────────────────────────────
                    EscrowActions(
                      escrow: escrow,
                      isSeller: isSeller,
                      onPayNow: () => _onPayNow(context, ref),
                      onGenerateLabel: () => _onGenerateLabel(context, ref),
                      onEnterTracking: () => _onEnterTracking(context, ref),
                      onConfirmDelivery: () =>
                          _onConfirmDelivery(context, ref),
                      onReportProblem: () =>
                          _onReportProblem(context, ref),
                    ),
                    const SizedBox(height: AppSpacing.lg),

                    // ── Event timeline ──────────────────────────────
                    if (escrow.events.isNotEmpty)
                      _EventTimeline(events: escrow.events),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAppBar(BuildContext context, EscrowState escrow) {
    return Container(
      padding: const EdgeInsetsDirectional.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.sm,
      ),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.arrow_back_ios_new_rounded, size: 20),
            onPressed: () => Navigator.of(context).maybePop(),
            color: AppColors.navy,
          ),
          const Expanded(
            child: Text(
              'تفاصيل الطلب',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppColors.navy,
              ),
            ),
          ),
          // Status badge
          Container(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xxs,
            ),
            decoration: BoxDecoration(
              color: _statusColor(escrow.status).withOpacity(0.12),
              borderRadius: AppSpacing.radiusFull,
            ),
            child: Text(
              _statusLabel(escrow.status),
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: _statusColor(escrow.status),
              ),
            ),
          ),
        ],
      ),
    );
  }

  void _onPayNow(BuildContext context, WidgetRef ref) {
    // Navigate to payment screen for this escrow
    Navigator.of(context).pushNamed(
      '/escrow/$escrowId/pay',
    );
  }

  void _onGenerateLabel(BuildContext context, WidgetRef ref) async {
    final notifier = ref.read(escrowProvider(escrowId).notifier);
    final labelUrl = await notifier.generateLabel();
    if (labelUrl != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('تم إنشاء بوليصة الشحن بنجاح'),
          backgroundColor: AppColors.emerald,
        ),
      );
    }
  }

  void _onEnterTracking(BuildContext context, WidgetRef ref) {
    ShippingForm.show(
      context: context,
      onSubmit: (trackingNumber, carrier) {
        ref
            .read(escrowProvider(escrowId).notifier)
            .submitTracking(trackingNumber, carrier);
      },
    );
  }

  void _onConfirmDelivery(BuildContext context, WidgetRef ref) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('تأكيد الاستلام'),
        content: const Text(
          'هل أنت متأكد من استلام المنتج بحالة جيدة؟\n\n'
          'سيتم تحرير المبلغ للبائع بعد التأكيد.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('إلغاء'),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              ref.read(escrowProvider(escrowId).notifier).confirmDelivery();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.emerald,
              foregroundColor: Colors.white,
            ),
            child: const Text('تأكيد'),
          ),
        ],
      ),
    );
  }

  void _onReportProblem(BuildContext context, WidgetRef ref) {
    DisputeFlow.show(
      context: context,
      onSubmit: (reason, photos) {
        ref
            .read(escrowProvider(escrowId).notifier)
            .openDispute(reason: reason, photos: photos);
      },
    );
  }

  Color _statusColor(String? status) => switch (status) {
        EscrowStatus.released => AppColors.emerald,
        EscrowStatus.disputed || EscrowStatus.refunded => AppColors.ember,
        EscrowStatus.paymentPending => AppColors.gold,
        EscrowStatus.inspectionPeriod => AppColors.gold,
        _ => AppColors.navy,
      };

  String _statusLabel(String? status) => switch (status) {
        EscrowStatus.paymentPending => 'بانتظار الدفع',
        EscrowStatus.paid => 'تم الدفع',
        EscrowStatus.shippingRequested => 'بانتظار الشحن',
        EscrowStatus.inTransit => 'في الطريق',
        EscrowStatus.inspectionPeriod => 'فترة الفحص',
        EscrowStatus.delivered => 'تم التسليم',
        EscrowStatus.released => 'تم الإفراج',
        EscrowStatus.disputed => 'نزاع',
        EscrowStatus.refunded => 'مسترد',
        _ => 'غير معروف',
      };
}

// ── Order summary card ──────────────────────────────────────────────

class _OrderSummaryCard extends StatelessWidget {
  const _OrderSummaryCard({required this.escrow});
  final EscrowState escrow;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: AppSpacing.horizontalMd,
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: AppSpacing.radiusMd,
        border: Border.all(color: AppColors.sand),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (escrow.listingTitle != null) ...[
            Text(
              escrow.listingTitle!,
              style: const TextStyle(
                fontSize: 16,
                fontWeight: FontWeight.w600,
                color: AppColors.navy,
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
          ],
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'المبلغ المحجوز',
                style: TextStyle(fontSize: 13, color: AppColors.mist),
              ),
              if (escrow.amount != null && escrow.currency != null)
                Text(
                  ArabicNumerals.formatCurrency(
                      escrow.amount!, escrow.currency!),
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w700,
                    color: AppColors.navy,
                    fontFamily: 'Sora',
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

// ── Tracking card ───────────────────────────────────────────────────

class _TrackingCard extends StatelessWidget {
  const _TrackingCard({required this.escrow});
  final EscrowState escrow;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: AppSpacing.horizontalMd,
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: AppColors.navy.withOpacity(0.04),
        borderRadius: AppSpacing.radiusMd,
      ),
      child: Row(
        children: [
          const Icon(Icons.local_shipping_rounded,
              color: AppColors.navy, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  escrow.carrier?.toUpperCase() ?? '',
                  style: const TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: AppColors.mist,
                    letterSpacing: 0.5,
                  ),
                ),
                Text(
                  escrow.trackingNumber ?? '',
                  textDirection: TextDirection.ltr,
                  style: const TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: AppColors.navy,
                    fontFamily: 'Sora',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Deadline card with live countdown ──────────────────────────────

class _DeadlineCard extends StatefulWidget {
  const _DeadlineCard({required this.escrow});
  final EscrowState escrow;

  @override
  State<_DeadlineCard> createState() => _DeadlineCardState();
}

class _DeadlineCardState extends State<_DeadlineCard> {
  Timer? _ticker;
  Duration _remaining = Duration.zero;

  @override
  void initState() {
    super.initState();
    _computeRemaining();
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) {
      _computeRemaining();
      if (mounted) setState(() {});
    });
  }

  @override
  void didUpdateWidget(_DeadlineCard old) {
    super.didUpdateWidget(old);
    _computeRemaining();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  void _computeRemaining() {
    final deadlineStr = _activeDeadlineStr;
    if (deadlineStr == null) {
      _remaining = Duration.zero;
      return;
    }
    final end = DateTime.tryParse(deadlineStr);
    if (end == null) {
      _remaining = Duration.zero;
      return;
    }
    final now = DateTime.now().toUtc();
    _remaining = end.difference(now);
    if (_remaining.isNegative) _remaining = Duration.zero;
  }

  String? get _activeDeadlineStr {
    if (widget.escrow.status == EscrowStatus.shippingRequested) {
      return widget.escrow.shippingDeadline;
    }
    if (widget.escrow.status == EscrowStatus.inspectionPeriod) {
      return widget.escrow.inspectionDeadline;
    }
    if (widget.escrow.status == EscrowStatus.paymentPending ||
        widget.escrow.status == EscrowStatus.paid) {
      return widget.escrow.paymentDeadline;
    }
    return null;
  }

  String get _deadlineLabel {
    if (widget.escrow.status == EscrowStatus.shippingRequested) {
      return 'الموعد النهائي للشحن';
    }
    if (widget.escrow.status == EscrowStatus.inspectionPeriod) {
      return 'ينتهي الفحص في';
    }
    return 'الموعد النهائي للدفع';
  }

  String get _formattedCountdown {
    if (_remaining <= Duration.zero) return 'انتهى الوقت';

    final hours = _remaining.inHours;
    final mins = _remaining.inMinutes.remainder(60);
    final secs = _remaining.inSeconds.remainder(60);

    if (hours > 0) {
      return '${hours}س ${mins}د';
    }
    return '${mins}د ${secs}ث';
  }

  /// Urgent (ember) when under 12 hours remaining.
  bool get _isUrgent => _remaining.inHours < 12 && _remaining > Duration.zero;

  @override
  Widget build(BuildContext context) {
    if (_activeDeadlineStr == null) return const SizedBox.shrink();

    final accentColor = _isUrgent ? AppColors.ember : AppColors.gold;

    return Container(
      margin: AppSpacing.horizontalMd,
      padding: AppSpacing.allMd,
      decoration: BoxDecoration(
        color: accentColor.withOpacity(0.08),
        borderRadius: AppSpacing.radiusMd,
      ),
      child: Row(
        children: [
          Icon(Icons.schedule_rounded, color: accentColor, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  _deadlineLabel,
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.mist,
                  ),
                ),
                Text(
                  _formattedCountdown,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: accentColor,
                    fontFamily: 'Sora',
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ── Event timeline ──────────────────────────────────────────────────

class _EventTimeline extends StatelessWidget {
  const _EventTimeline({required this.events});
  final List<EscrowEvent> events;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: AppSpacing.horizontalMd,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'سجل الأحداث',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          ...events.asMap().entries.map((entry) {
            final event = entry.value;
            final isLast = entry.key == events.length - 1;
            return _TimelineItem(event: event, isLast: isLast);
          }),
        ],
      ),
    );
  }
}

class _TimelineItem extends StatelessWidget {
  const _TimelineItem({required this.event, required this.isLast});

  final EscrowEvent event;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Timeline dot + line
          SizedBox(
            width: 24,
            child: Column(
              children: [
                Container(
                  width: 10,
                  height: 10,
                  margin: const EdgeInsetsDirectional.only(top: 4),
                  decoration: const BoxDecoration(
                    color: AppColors.navy,
                    shape: BoxShape.circle,
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(
                      width: 1.5,
                      color: AppColors.sand,
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          // Event content
          Expanded(
            child: Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _eventLabel(event.type),
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppColors.ink,
                    ),
                  ),
                  if (event.details != null)
                    Padding(
                      padding:
                          const EdgeInsetsDirectional.only(top: AppSpacing.xxs),
                      child: Text(
                        event.details!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.mist,
                        ),
                      ),
                    ),
                  Text(
                    event.timestamp,
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppColors.mist,
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

  String _eventLabel(String type) => switch (type) {
        'payment_received' => 'تم استلام الدفع',
        'shipping_requested' => 'تم طلب الشحن',
        'tracking_submitted' => 'تم إدخال رقم التتبع',
        'in_transit' => 'الشحنة في الطريق',
        'delivered' => 'تم التسليم',
        'delivery_confirmed' => 'تم تأكيد الاستلام',
        'funds_released' => 'تم تحرير المبلغ',
        'dispute_opened' => 'تم فتح نزاع',
        'dispute_resolved' => 'تم حل النزاع',
        'refunded' => 'تم الاسترداد',
        _ => type,
      };
}
