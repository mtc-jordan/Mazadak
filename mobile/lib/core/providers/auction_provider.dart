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
    this.timerRemaining,
    this.status = 'unknown',
    this.lastBidder,
    this.sellerId,
    this.extensionCount = 0,
    this.connectionStatus = ConnectionStatus.disconnected,
    this.error,
    this.bids = const [],
    this.minIncrement = 25.0,
    this.currency = 'JOD',
    this.listingTitle,
    this.imageUrl,
    this.timerExtended = false,
    this.watcherCount = 0,
  });

  final String? auctionId;
  final double currentPrice;
  final int bidCount;
  final String? winnerId;
  final String? endsAt;
  final int? timerRemaining; // server-provided TTL in seconds
  final String status;
  final String? lastBidder;
  final String? sellerId;
  final int extensionCount;
  final ConnectionStatus connectionStatus;
  final String? error;
  final List<BidEntry> bids;
  final double minIncrement;
  final String currency;
  final String? listingTitle;
  final String? imageUrl;
  final bool timerExtended;
  final int watcherCount;

  bool get isConnected => connectionStatus == ConnectionStatus.connected;

  /// Whether the current user is the seller (cannot bid).
  bool isSeller(String? currentUserId) =>
      sellerId != null && sellerId == currentUserId;

  AuctionState copyWith({
    String? auctionId,
    double? currentPrice,
    int? bidCount,
    String? winnerId,
    String? endsAt,
    int? timerRemaining,
    String? status,
    String? lastBidder,
    String? sellerId,
    int? extensionCount,
    ConnectionStatus? connectionStatus,
    String? error,
    List<BidEntry>? bids,
    double? minIncrement,
    String? currency,
    String? listingTitle,
    String? imageUrl,
    bool? timerExtended,
    int? watcherCount,
  }) => AuctionState(
        auctionId: auctionId ?? this.auctionId,
        currentPrice: currentPrice ?? this.currentPrice,
        bidCount: bidCount ?? this.bidCount,
        winnerId: winnerId ?? this.winnerId,
        endsAt: endsAt ?? this.endsAt,
        timerRemaining: timerRemaining ?? this.timerRemaining,
        status: status ?? this.status,
        lastBidder: lastBidder ?? this.lastBidder,
        sellerId: sellerId ?? this.sellerId,
        extensionCount: extensionCount ?? this.extensionCount,
        connectionStatus: connectionStatus ?? this.connectionStatus,
        error: error,
        bids: bids ?? this.bids,
        minIncrement: minIncrement ?? this.minIncrement,
        currency: currency ?? this.currency,
        listingTitle: listingTitle ?? this.listingTitle,
        imageUrl: imageUrl ?? this.imageUrl,
        timerExtended: timerExtended ?? this.timerExtended,
        watcherCount: watcherCount ?? this.watcherCount,
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
      // ── Socket.IO lifecycle events (from WsClient) ──────────
      case '_connected':
        state = state.copyWith(connectionStatus: ConnectionStatus.connected);
      case '_disconnected':
        state = state.copyWith(connectionStatus: ConnectionStatus.disconnected);

      // ── Auction events (SDD §7.2) ──────────────────────────
      case 'current_state':
        _handleCurrentState(msg);
      case 'bid_update':
        _handleBidUpdate(msg);
      case 'bid_confirmed':
        _handleBidConfirmed(msg);
      case 'bid_rejected':
        _handleBidRejected(msg);
      case 'timer_extended':
        _handleTimerExtended(msg);
      case 'watcher_update':
        state = state.copyWith(
          watcherCount: msg['watcher_count'] as int? ?? state.watcherCount,
        );
      case 'auction_ended':
        state = state.copyWith(
          status: 'ended',
          winnerId: msg['winner_id'] as String?,
          currentPrice:
              (msg['final_price'] as num?)?.toDouble() ?? state.currentPrice,
        );
      case 'error':
        state = state.copyWith(error: msg['detail'] as String?);
    }
  }

  /// 'bid_update' — broadcast to all participants when any bid is accepted.
  void _handleBidUpdate(Map<String, dynamic> msg) {
    final newPrice = (msg['current_price'] as num? ?? msg['amount'] as num).toDouble();
    final bidderId = msg['user_id'] as String? ?? '';
    final myId = _currentUserId;
    final isOwn = bidderId == myId;

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
      timerRemaining: msg['remaining_seconds'] as int?,
      bids: bids,
    );
  }

  /// 'bid_confirmed' — sent only to the bidder who placed the bid.
  void _handleBidConfirmed(Map<String, dynamic> msg) {
    _cancelOptimisticRollback();
    // The bid_update event handles the actual state update for all clients.
    // This event just confirms our optimistic bid was accepted.
  }

  /// 'bid_rejected' — sent only to the bidder whose bid was rejected.
  void _handleBidRejected(Map<String, dynamic> msg) {
    _rollbackOptimistic();
    final reason = msg['reason'] as String? ?? 'مزايدة مرفوضة';
    state = state.copyWith(error: reason);
  }

  void _handleTimerExtended(Map<String, dynamic> msg) {
    _timerExtendedDismiss?.cancel();

    state = state.copyWith(
      timerRemaining: msg['remaining_seconds'] as int?,
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

  /// 'current_state' — full state reconciliation on connect/reconnect.
  /// Contains all values: price, bid_count, timer_remaining, watcher_count,
  /// last_20_bids, seller_id, etc.
  void _handleCurrentState(Map<String, dynamic> msg) {
    final bidHistory = (msg['last_20_bids'] as List? ?? msg['recent_bids'] as List?)
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
      currentPrice: (msg['current_price'] as num? ?? msg['price'] as num?)?.toDouble() ?? state.currentPrice,
      bidCount: msg['bid_count'] as int? ?? 0,
      timerRemaining: msg['remaining_seconds'] as int?,
      endsAt: msg['ends_at'] as String?,
      status: msg['status'] as String? ?? state.status,
      winnerId: msg['winner_id'] as String?,
      sellerId: msg['seller_id'] as String?,
      minIncrement: (msg['min_increment'] as num?)?.toDouble() ?? state.minIncrement,
      currency: msg['currency'] as String? ?? state.currency,
      listingTitle: msg['listing_title'] as String? ?? state.listingTitle,
      imageUrl: msg['image_url'] as String? ?? state.imageUrl,
      bids: bidHistory,
      watcherCount: msg['watcher_count'] as int? ?? state.watcherCount,
      connectionStatus: ConnectionStatus.connected,
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

    // Emit bid via Socket.IO — amount in CENTS (integer)
    wsClient.emit('place_bid', {
      'auction_id': auctionId,
      'amount': (amount * 100).round(),
    });
    // Server will confirm via 'bid_confirmed' or reject via 'bid_rejected'
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

