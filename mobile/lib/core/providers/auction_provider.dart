import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/ws_client.dart';
import 'auth_provider.dart';
import 'core_providers.dart';

// ═══════════════════════════════════════════════════════════════════
//  Connection status
// ═══════════════════════════════════════════════════════════════════

enum ConnectionStatus { connected, disconnected, reconnecting }

// ═══════════════════════════════════════════════════════════════════
//  Bid entry for history feed
// ═══════════════════════════════════════════════════════════════════

class BidEntry {
  const BidEntry({
    required this.userId,
    required this.amount,
    required this.timestamp,
    this.isOwn = false,
    this.isPending = false,
  });

  final String userId;
  final double amount;
  final DateTime timestamp;
  final bool isOwn;
  final bool isPending; // optimistic bid not yet confirmed

  BidEntry copyWith({bool? isPending}) => BidEntry(
        userId: userId,
        amount: amount,
        timestamp: timestamp,
        isOwn: isOwn,
        isPending: isPending ?? this.isPending,
      );
}

// ═══════════════════════════════════════════════════════════════════
//  Auction state
// ═══════════════════════════════════════════════════════════════════

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
    this.connectionStatus = ConnectionStatus.disconnected,
    this.error,
    this.bids = const [],
    this.minIncrement = 25.0,
    this.currency = 'JOD',
    this.listingTitle,
    this.imageUrl,
    this.timerExtended = false,
  });

  final String? auctionId;
  final double currentPrice;
  final int bidCount;
  final String? winnerId;
  final String? endsAt;
  final String status;
  final String? lastBidder;
  final int extensionCount;
  final ConnectionStatus connectionStatus;
  final String? error;
  final List<BidEntry> bids;
  final double minIncrement;
  final String currency;
  final String? listingTitle;
  final String? imageUrl;
  final bool timerExtended;

  bool get isConnected => connectionStatus == ConnectionStatus.connected;

  AuctionState copyWith({
    String? auctionId,
    double? currentPrice,
    int? bidCount,
    String? winnerId,
    String? endsAt,
    String? status,
    String? lastBidder,
    int? extensionCount,
    ConnectionStatus? connectionStatus,
    String? error,
    List<BidEntry>? bids,
    double? minIncrement,
    String? currency,
    String? listingTitle,
    String? imageUrl,
    bool? timerExtended,
  }) => AuctionState(
        auctionId: auctionId ?? this.auctionId,
        currentPrice: currentPrice ?? this.currentPrice,
        bidCount: bidCount ?? this.bidCount,
        winnerId: winnerId ?? this.winnerId,
        endsAt: endsAt ?? this.endsAt,
        status: status ?? this.status,
        lastBidder: lastBidder ?? this.lastBidder,
        extensionCount: extensionCount ?? this.extensionCount,
        connectionStatus: connectionStatus ?? this.connectionStatus,
        error: error,
        bids: bids ?? this.bids,
        minIncrement: minIncrement ?? this.minIncrement,
        currency: currency ?? this.currency,
        listingTitle: listingTitle ?? this.listingTitle,
        imageUrl: imageUrl ?? this.imageUrl,
        timerExtended: timerExtended ?? this.timerExtended,
      );
}

// ═══════════════════════════════════════════════════════════════════
//  Auction provider — SDD §7.1 auctionProvider(id) as StreamNotifier
// ═══════════════════════════════════════════════════════════════════

/// Max bid history entries kept in memory.
const _maxBidHistory = 50;

/// Timeout for optimistic bid rollback.
const _optimisticTimeout = Duration(seconds: 3);

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
  Timer? _optimisticRollbackTimer;
  Timer? _timerExtendedDismiss;
  double? _preOptimisticPrice;

  /// Current user's ID (from auth provider).
  String? get _currentUserId => ref.read(authProvider).userId;

  Future<void> _connect() async {
    state = state.copyWith(connectionStatus: ConnectionStatus.reconnecting);
    try {
      final stream = await wsClient.connect(auctionId);
      state = state.copyWith(connectionStatus: ConnectionStatus.connected);

      _subscription = stream.listen(
        _onMessage,
        onError: (e) {
          state = state.copyWith(
            connectionStatus: ConnectionStatus.disconnected,
            error: e.toString(),
          );
        },
        onDone: () {
          state = state.copyWith(
            connectionStatus: ConnectionStatus.disconnected,
          );
        },
      );
    } catch (e) {
      state = state.copyWith(
        connectionStatus: ConnectionStatus.disconnected,
        error: e.toString(),
      );
    }
  }

  void _onMessage(Map<String, dynamic> msg) {
    final type = msg['type'] as String? ?? '';

    switch (type) {
      case 'bid_accepted':
        _handleBidAccepted(msg);
      case 'anti_snipe':
      case 'timer_extended':
        _handleTimerExtended(msg);
      case 'auction_ended':
        state = state.copyWith(
          status: 'ended',
          winnerId: msg['winner_id'] as String?,
          currentPrice:
              (msg['final_price'] as num?)?.toDouble() ?? state.currentPrice,
        );
      case 'snapshot':
        _handleSnapshot(msg);
      case 'error':
        state = state.copyWith(error: msg['detail'] as String?);
    }
  }

  void _handleBidAccepted(Map<String, dynamic> msg) {
    final newPrice = (msg['current_price'] as num).toDouble();
    final bidderId = msg['user_id'] as String? ?? '';
    final myId = _currentUserId;
    final isOwn = bidderId == myId;

    // Cancel optimistic rollback if server confirmed our bid
    if (isOwn) {
      _cancelOptimisticRollback();
    }

    // Remove any pending optimistic entry for this price
    final updatedBids = state.bids
        .where((b) => !(b.isPending && b.amount == newPrice && b.isOwn))
        .toList();

    final newBid = BidEntry(
      userId: bidderId,
      amount: newPrice,
      timestamp: DateTime.now(),
      isOwn: isOwn,
    );

    final bids = [newBid, ...updatedBids];
    if (bids.length > _maxBidHistory) {
      bids.removeRange(_maxBidHistory, bids.length);
    }

    state = state.copyWith(
      currentPrice: newPrice,
      bidCount: msg['bid_count'] as int? ?? state.bidCount + 1,
      lastBidder: bidderId,
      bids: bids,
    );
  }

  void _handleTimerExtended(Map<String, dynamic> msg) {
    _timerExtendedDismiss?.cancel();

    state = state.copyWith(
      endsAt: msg['new_ends_at'] as String?,
      extensionCount:
          msg['extension_count'] as int? ?? state.extensionCount + 1,
      timerExtended: true,
    );

    // Auto-dismiss the Extended banner after 5 seconds
    _timerExtendedDismiss = Timer(const Duration(seconds: 5), () {
      if (mounted) {
        state = state.copyWith(timerExtended: false);
      }
    });
  }

  void _handleSnapshot(Map<String, dynamic> msg) {
    // Full state reconciliation on reconnect
    final bidHistory = (msg['recent_bids'] as List?)
            ?.map((b) {
              final m = b as Map<String, dynamic>;
              return BidEntry(
                userId: m['user_id'] as String? ?? '',
                amount: (m['amount'] as num).toDouble(),
                timestamp: DateTime.tryParse(m['created_at'] as String? ?? '') ??
                    DateTime.now(),
                isOwn: m['user_id'] == _currentUserId,
              );
            })
            .toList() ??
        state.bids;

    state = state.copyWith(
      currentPrice: (msg['current_price'] as num).toDouble(),
      bidCount: msg['bid_count'] as int? ?? 0,
      endsAt: msg['ends_at'] as String?,
      status: msg['status'] as String? ?? state.status,
      winnerId: msg['winner_id'] as String?,
      minIncrement: (msg['min_increment'] as num?)?.toDouble() ?? state.minIncrement,
      currency: msg['currency'] as String? ?? state.currency,
      listingTitle: msg['listing_title'] as String? ?? state.listingTitle,
      imageUrl: msg['image_url'] as String? ?? state.imageUrl,
      bids: bidHistory,
    );
  }

  // ── Public API ──────────────────────────────────────────────────

  /// Place a bid with optimistic update.
  ///
  /// Shows the bid immediately in the feed. If no server confirmation
  /// arrives within 3 seconds, rolls back to the pre-bid state.
  Future<void> placeBid(double amount) async {
    final myId = _currentUserId ?? 'me';
    _preOptimisticPrice = state.currentPrice;

    // Optimistic: add pending bid entry
    final optimisticBid = BidEntry(
      userId: myId,
      amount: amount,
      timestamp: DateTime.now(),
      isOwn: true,
      isPending: true,
    );

    final bids = [optimisticBid, ...state.bids];
    if (bids.length > _maxBidHistory) {
      bids.removeRange(_maxBidHistory, bids.length);
    }

    state = state.copyWith(
      currentPrice: amount,
      bids: bids,
      error: null,
    );

    // Start rollback timer
    _optimisticRollbackTimer = Timer(_optimisticTimeout, _rollbackOptimistic);

    // Fire REST call
    try {
      final api = ref.read(apiClientProvider);
      await api.post('/auctions/$auctionId/bid', data: {'amount': amount});
      // Server will confirm via WebSocket 'bid_accepted'
    } catch (e) {
      _rollbackOptimistic();
      state = state.copyWith(error: e.toString());
    }
  }

  void _rollbackOptimistic() {
    _cancelOptimisticRollback();
    if (_preOptimisticPrice != null) {
      // Remove pending bids and restore price
      final bids = state.bids.where((b) => !b.isPending).toList();
      state = state.copyWith(
        currentPrice: _preOptimisticPrice,
        bids: bids,
      );
      _preOptimisticPrice = null;
    }
  }

  void _cancelOptimisticRollback() {
    _optimisticRollbackTimer?.cancel();
    _optimisticRollbackTimer = null;
    _preOptimisticPrice = null;
  }

  void disconnect() {
    _subscription?.cancel();
    _optimisticRollbackTimer?.cancel();
    _timerExtendedDismiss?.cancel();
    wsClient.disconnect();
  }
}

