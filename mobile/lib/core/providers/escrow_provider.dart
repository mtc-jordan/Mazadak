import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import 'core_providers.dart';

/// Escrow status constants matching backend enum.
abstract final class EscrowStatus {
  static const paymentPending = 'PAYMENT_PENDING';
  static const paid = 'PAID';
  static const shippingRequested = 'SHIPPING_REQUESTED';
  static const inTransit = 'IN_TRANSIT';
  static const inspectionPeriod = 'INSPECTION_PERIOD';
  static const delivered = 'DELIVERED';
  static const released = 'RELEASED';
  static const disputed = 'DISPUTED';
  static const refunded = 'REFUNDED';
}

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
    this.trackingUrl,
    this.events = const [],
    this.isLoading = false,
    this.error,
    this.listingTitle,
    this.listingImageUrl,
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
  final String? trackingUrl;
  final List<EscrowEvent> events;
  final bool isLoading;
  final String? error;
  final String? listingTitle;
  final String? listingImageUrl;

  /// The 5-step progress index (0-based).
  int get stepIndex => switch (status) {
        EscrowStatus.paymentPending => 0,
        EscrowStatus.paid => 0,
        EscrowStatus.shippingRequested => 1,
        EscrowStatus.inTransit => 2,
        EscrowStatus.inspectionPeriod || EscrowStatus.delivered => 3,
        EscrowStatus.released => 4,
        _ => 0,
      };

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
    String? trackingUrl,
    List<EscrowEvent>? events,
    bool? isLoading,
    String? error,
    String? listingTitle,
    String? listingImageUrl,
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
        trackingUrl: trackingUrl ?? this.trackingUrl,
        events: events ?? this.events,
        isLoading: isLoading ?? this.isLoading,
        error: error,
        listingTitle: listingTitle ?? this.listingTitle,
        listingImageUrl: listingImageUrl ?? this.listingImageUrl,
      );
}

/// Single event in the escrow timeline.
class EscrowEvent {
  const EscrowEvent({
    required this.type,
    required this.timestamp,
    this.actor,
    this.details,
  });

  factory EscrowEvent.fromJson(Map<String, dynamic> json) => EscrowEvent(
        type: json['type'] as String,
        timestamp: json['timestamp'] as String,
        actor: json['actor'] as String?,
        details: json['details'] as String?,
      );

  final String type;
  final String timestamp;
  final String? actor;
  final String? details;
}

/// Escrow provider — SDD §7.1 escrowProvider(id).
///
/// Fetches and tracks escrow state for a specific transaction.
/// Polls every 30s while screen is open. Auto-disposes on leave.
final escrowProvider = StateNotifierProvider.autoDispose
    .family<EscrowNotifier, EscrowState, String>((ref, escrowId) {
  final notifier = EscrowNotifier(escrowId: escrowId, ref: ref);
  ref.onDispose(notifier.dispose);
  return notifier;
});

class EscrowNotifier extends StateNotifier<EscrowState> {
  EscrowNotifier({required this.escrowId, required this.ref})
      : super(EscrowState(escrowId: escrowId)) {
    loadEscrow();
    _startPolling();
  }

  final String escrowId;
  final Ref ref;
  Timer? _pollTimer;

  void _startPolling() {
    _pollTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted) loadEscrow();
    });
  }

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
        trackingUrl: data['tracking_url'] as String?,
        listingTitle: data['listing_title'] as String?,
        listingImageUrl: data['listing_image_url'] as String?,
        events: (data['events'] as List?)
                ?.map((e) =>
                    EscrowEvent.fromJson(e as Map<String, dynamic>))
                .toList() ??
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
      await api.post('/escrow/$escrowId/confirm-receipt');
      await loadEscrow();
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  /// Submit tracking number (seller action).
  Future<void> submitTracking(String trackingNumber, String carrier) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = ref.read(apiClientProvider);
      await api.post('/escrow/$escrowId/tracking', data: {
        'tracking_number': trackingNumber,
        'carrier': carrier,
      });
      await loadEscrow();
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  /// Generate Aramex shipping label (seller action).
  Future<String?> generateLabel() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = ref.read(apiClientProvider);
      final resp = await api.post('/escrow/$escrowId/generate-label');
      final data = resp.data as Map<String, dynamic>;
      await loadEscrow();
      return data['label_url'] as String?;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
      return null;
    }
  }

  /// Open dispute with reason and photo evidence.
  ///
  /// Photos are hashed with SHA-256 client-side before upload.
  Future<void> openDispute({
    required String reason,
    required List<XFile> photos,
  }) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = ref.read(apiClientProvider);

      // Build multipart form with SHA-256 hashes
      final formData = FormData();
      formData.fields.add(MapEntry('reason', reason));

      for (final photo in photos) {
        final bytes = await photo.readAsBytes();

        // Compute SHA-256 hash client-side
        final hash = sha256.convert(bytes).toString();
        formData.fields.add(MapEntry('hashes[]', hash));

        formData.files.add(MapEntry(
          'photos[]',
          MultipartFile.fromBytes(
            bytes,
            filename: photo.name,
          ),
        ));
      }

      await api.post(
        '/escrow/$escrowId/dispute',
        data: formData,
        options: Options(contentType: 'multipart/form-data'),
      );
      await loadEscrow();
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }
}
