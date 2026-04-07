import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/ws_client.dart';
import 'core_providers.dart';

/// Real-time auction state pushed via WebSocket.
class AuctionState {
  const AuctionState({
    this.auctionId,
    this.currentPrice = 0,
    this.bidCount = 0,
    this.winnerId,
    this.endsAt,
    this.status = 'unknown',
    this.lastBidder,
    this.extensionCount = 0,
    this.isConnected = false,
    this.error,
  });

  final String? auctionId;
  final double currentPrice;
  final int bidCount;
  final String? winnerId;
  final String? endsAt;
  final String status;
  final String? lastBidder;
  final int extensionCount;
  final bool isConnected;
  final String? error;

  AuctionState copyWith({
    String? auctionId,
    double? currentPrice,
    int? bidCount,
    String? winnerId,
    String? endsAt,
    String? status,
    String? lastBidder,
    int? extensionCount,
    bool? isConnected,
    String? error,
  }) => AuctionState(
        auctionId: auctionId ?? this.auctionId,
        currentPrice: currentPrice ?? this.currentPrice,
        bidCount: bidCount ?? this.bidCount,
        winnerId: winnerId ?? this.winnerId,
        endsAt: endsAt ?? this.endsAt,
        status: status ?? this.status,
        lastBidder: lastBidder ?? this.lastBidder,
        extensionCount: extensionCount ?? this.extensionCount,
        isConnected: isConnected ?? this.isConnected,
        error: error,
      );
}

/// Auction provider — SDD §7.1 auctionProvider(id) as StreamNotifier.
///
/// Connects to WebSocket for real-time bid updates. Auto-disposes
/// when the auction screen is popped (family + autoDispose).
final auctionProvider = StateNotifierProvider.autoDispose
    .family<AuctionNotifier, AuctionState, String>((ref, auctionId) {
  final notifier = AuctionNotifier(
    auctionId: auctionId,
    wsClient: ref.watch(wsClientProvider),
    ref: ref,
  );

  ref.onDispose(() => notifier.disconnect());

  return notifier;
});

class AuctionNotifier extends StateNotifier<AuctionState> {
  AuctionNotifier({
    required this.auctionId,
    required this.wsClient,
    required this.ref,
  }) : super(AuctionState(auctionId: auctionId)) {
    _connect();
  }

  final String auctionId;
  final WsClient wsClient;
  final Ref ref;
  StreamSubscription<Map<String, dynamic>>? _subscription;

  Future<void> _connect() async {
    try {
      final stream = await wsClient.connect(auctionId);
      state = state.copyWith(isConnected: true);

      _subscription = stream.listen(
        _onMessage,
        onError: (e) {
          state = state.copyWith(isConnected: false, error: e.toString());
        },
        onDone: () {
          state = state.copyWith(isConnected: false);
        },
      );
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  void _onMessage(Map<String, dynamic> msg) {
    final type = msg['type'] as String? ?? '';

    switch (type) {
      case 'bid_accepted':
        state = state.copyWith(
          currentPrice: (msg['current_price'] as num).toDouble(),
          bidCount: msg['bid_count'] as int? ?? state.bidCount + 1,
          lastBidder: msg['user_id'] as String?,
        );
      case 'anti_snipe':
        state = state.copyWith(
          endsAt: msg['new_ends_at'] as String?,
          extensionCount: msg['extension_count'] as int? ?? state.extensionCount + 1,
        );
      case 'auction_ended':
        state = state.copyWith(
          status: 'ended',
          winnerId: msg['winner_id'] as String?,
          currentPrice: (msg['final_price'] as num?)?.toDouble() ?? state.currentPrice,
        );
      case 'snapshot':
        state = state.copyWith(
          currentPrice: (msg['current_price'] as num).toDouble(),
          bidCount: msg['bid_count'] as int? ?? 0,
          endsAt: msg['ends_at'] as String?,
          status: msg['status'] as String? ?? state.status,
          winnerId: msg['winner_id'] as String?,
        );
      case 'error':
        state = state.copyWith(error: msg['detail'] as String?);
    }
  }

  /// Place a bid via REST (not WebSocket) — server validates via Lua.
  Future<void> placeBid(double amount) async {
    state = state.copyWith(error: null);
    try {
      final api = ref.read(apiClientProvider);
      await api.post('/auctions/$auctionId/bid', data: {'amount': amount});
      // Server confirms via WebSocket 'bid_accepted' — no optimistic update
    } catch (e) {
      state = state.copyWith(error: e.toString());
    }
  }

  void disconnect() {
    _subscription?.cancel();
    wsClient.disconnect();
  }
}
