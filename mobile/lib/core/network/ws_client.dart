import 'dart:async';
import 'dart:math';

import 'package:socket_io_client/socket_io_client.dart' as io;

import 'token_storage.dart';

/// Socket.IO base URL — override via --dart-define=WS_BASE_URL=...
const _defaultBaseUrl = 'http://10.0.2.2:8000'; // Android emulator

String get _baseUrl =>
    const String.fromEnvironment('WS_BASE_URL', defaultValue: _defaultBaseUrl);

/// Socket.IO client for real-time auction updates.
///
/// Connects to namespace '/auction' with JWT token in auth param.
/// Automatically reconnects on disconnect with exponential backoff:
/// 1s → 2s → 4s → 8s → 16s → 30s cap.
class WsClient {
  WsClient({required this.tokenStorage});

  final TokenStorage tokenStorage;
  io.Socket? _socket;
  StreamController<Map<String, dynamic>>? _controller;
  String? _currentAuctionId;
  int _reconnectAttempts = 0;

  /// Connect to an auction room and return a broadcast stream of messages.
  Future<Stream<Map<String, dynamic>>> connect(String auctionId) async {
    _currentAuctionId = auctionId;
    _reconnectAttempts = 0;
    _controller = StreamController<Map<String, dynamic>>.broadcast();

    await _doConnect(auctionId);
    return _controller!.stream;
  }

  Future<void> _doConnect(String auctionId) async {
    // Dispose previous socket on reconnect to prevent leaks
    _socket?.dispose();

    final token = await tokenStorage.accessToken;

    _socket = io.io(
      _baseUrl,
      io.OptionBuilder()
          .setTransports(['websocket'])
          .setPath('/socket.io')
          .setAuth({'token': token, 'auction_id': auctionId})
          .disableAutoConnect()
          .disableReconnection()
          .build(),
    );
    _socket!.nsp = '/auction';

    _socket!.onConnect((_) {
      _reconnectAttempts = 0;
      _controller?.add({'type': '_connected'});
      // Server emits current_state automatically on connect — no client emit needed
    });

    _socket!.onDisconnect((_) {
      _controller?.add({'type': '_disconnected'});
      _scheduleReconnect();
    });

    _socket!.onConnectError((_) {
      _controller?.add({'type': '_disconnected'});
      _scheduleReconnect();
    });

    // Forward all auction events to the stream
    for (final event in [
      'current_state',
      'bid_update',
      'bid_confirmed',
      'bid_rejected',
      'timer_extended',
      'watcher_update',
      'auction_ended',
      'pong',
      'error',
    ]) {
      _socket!.on(event, (data) {
        final msg = data is Map<String, dynamic>
            ? data
            : <String, dynamic>{};
        msg['type'] = event;
        _controller?.add(msg);
      });
    }

    _socket!.connect();
  }

  /// Emit an event through the Socket.IO connection.
  void emit(String event, Map<String, dynamic> data) {
    _socket?.emit(event, data);
  }

  /// Send a JSON message (legacy compat — prefer emit).
  void send(Map<String, dynamic> message) {
    final type = message.remove('type') as String? ?? 'message';
    _socket?.emit(type, message);
  }

  /// Disconnect and clean up.
  void disconnect() {
    _socket?.dispose();
    _controller?.close();
    _socket = null;
    _controller = null;
    _currentAuctionId = null;
  }

  /// Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s cap.
  void _scheduleReconnect() {
    if (_currentAuctionId == null || (_controller?.isClosed ?? true)) return;

    _reconnectAttempts++;
    final delaySec = min(pow(2, _reconnectAttempts - 1).toInt(), 30);
    final delay = Duration(seconds: delaySec);

    Future.delayed(delay, () {
      if (_currentAuctionId != null && !(_controller?.isClosed ?? true)) {
        _doConnect(_currentAuctionId!);
      }
    });
  }
}
