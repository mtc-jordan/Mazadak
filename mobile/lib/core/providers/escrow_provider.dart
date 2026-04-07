import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';

/// Escrow state for a specific transaction.
class EscrowState {
  const EscrowState({
    this.escrowId,
    this.status,
    this.buyerId,
    this.sellerId,
    this.amount,
    this.currency,
    this.paymentDeadline,
    this.shippingDeadline,
    this.inspectionDeadline,
    this.trackingNumber,
    this.carrier,
    this.events = const [],
    this.isLoading = false,
    this.error,
  });

  final String? escrowId;
  final String? status;
  final String? buyerId;
  final String? sellerId;
  final double? amount;
  final String? currency;
  final String? paymentDeadline;
  final String? shippingDeadline;
  final String? inspectionDeadline;
  final String? trackingNumber;
  final String? carrier;
  final List<Map<String, dynamic>> events;
  final bool isLoading;
  final String? error;

  EscrowState copyWith({
    String? escrowId,
    String? status,
    String? buyerId,
    String? sellerId,
    double? amount,
    String? currency,
    String? paymentDeadline,
    String? shippingDeadline,
    String? inspectionDeadline,
    String? trackingNumber,
    String? carrier,
    List<Map<String, dynamic>>? events,
    bool? isLoading,
    String? error,
  }) => EscrowState(
        escrowId: escrowId ?? this.escrowId,
        status: status ?? this.status,
        buyerId: buyerId ?? this.buyerId,
        sellerId: sellerId ?? this.sellerId,
        amount: amount ?? this.amount,
        currency: currency ?? this.currency,
        paymentDeadline: paymentDeadline ?? this.paymentDeadline,
        shippingDeadline: shippingDeadline ?? this.shippingDeadline,
        inspectionDeadline: inspectionDeadline ?? this.inspectionDeadline,
        trackingNumber: trackingNumber ?? this.trackingNumber,
        carrier: carrier ?? this.carrier,
        events: events ?? this.events,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

/// Escrow provider — SDD §7.1 escrowProvider(id).
///
/// Fetches and tracks escrow state for a specific transaction.
/// Auto-disposes when the user leaves the escrow detail screen.
final escrowProvider = StateNotifierProvider.autoDispose
    .family<EscrowNotifier, EscrowState, String>((ref, escrowId) {
  return EscrowNotifier(escrowId: escrowId, ref: ref);
});

class EscrowNotifier extends StateNotifier<EscrowState> {
  EscrowNotifier({required this.escrowId, required this.ref})
      : super(EscrowState(escrowId: escrowId)) {
    loadEscrow();
  }

  final String escrowId;
  final Ref ref;

  Future<void> loadEscrow() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.get('/escrow/$escrowId');
      final data = resp.data as Map<String, dynamic>;

      state = EscrowState(
        escrowId: escrowId,
        status: data['status'] as String?,
        buyerId: data['buyer_id'] as String?,
        sellerId: data['seller_id'] as String?,
        amount: (data['amount'] as num?)?.toDouble(),
        currency: data['currency'] as String?,
        paymentDeadline: data['payment_deadline'] as String?,
        shippingDeadline: data['shipping_deadline'] as String?,
        inspectionDeadline: data['inspection_deadline'] as String?,
        trackingNumber: data['tracking_number'] as String?,
        carrier: data['carrier'] as String?,
        events: (data['events'] as List?)
                ?.cast<Map<String, dynamic>>() ??
            const [],
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  /// Confirm delivery (buyer action).
  Future<void> confirmDelivery() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = ref.read(apiClientProvider);
      await api.post('/escrow/$escrowId/confirm-delivery');
      await loadEscrow();
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  /// Open dispute (buyer action).
  Future<void> openDispute(String reason) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = ref.read(apiClientProvider);
      await api.post('/escrow/$escrowId/dispute', data: {'reason': reason});
      await loadEscrow();
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }
}
