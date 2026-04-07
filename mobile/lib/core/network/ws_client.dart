import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

import 'token_storage.dart';

/// WebSocket base URL — override via --dart-define=WS_BASE_URL=...
const _defaultWsUrl = 'ws://10.0.2.2:8000/api/v1/ws'; // Android emulator

String get _wsBaseUrl =>
    const String.fromEnvironment('WS_BASE_URL', defaultValue: _defaultWsUrl);

/// WebSocket client for real-time auction updates.
///
/// Connects to `/ws/auction/{auctionId}` with JWT token as query param.
/// Automatically reconnects on disconnect with exponential backoff.
class WsClient {
  WsClient({required this.tokenStorage});

  final TokenStorage tokenStorage;
  WebSocketChannel? _channel;
  StreamController<Map<String, dynamic>>? _controller;
  Timer? _reconnectTimer;
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
    final token = await tokenStorage.accessToken;
    final uri = Uri.parse('$_wsBaseUrl/auction/$auctionId?token=$token');

    _channel = WebSocketChannel.connect(uri);

    _channel!.stream.listen(
      (data) {
        try {
          final decoded = jsonDecode(data as String) as Map<String, dynamic>;
          _controller?.add(decoded);
          _reconnectAttempts = 0;
        } catch (_) {
          // Ignore malformed messages
        }
      },
      onDone: () => _scheduleReconnect(),
      onError: (_) => _scheduleReconnect(),
    );
  }

  /// Send a JSON message through the WebSocket.
  void send(Map<String, dynamic> message) {
    _channel?.sink.add(jsonEncode(message));
  }

  /// Disconnect and clean up.
  void disconnect() {
    _reconnectTimer?.cancel();
    _channel?.sink.close();
    _controller?.close();
    _channel = null;
    _controller = null;
    _currentAuctionId = null;
  }

  void _scheduleReconnect() {
    if (_currentAuctionId == null || (_controller?.isClosed ?? true)) return;

    _reconnectAttempts++;
    final delay = Duration(
      seconds: (_reconnectAttempts * 2).clamp(1, 30),
    );

    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, () {
      if (_currentAuctionId != null) {
        _doConnect(_currentAuctionId!);
      }
    });
  }
}
