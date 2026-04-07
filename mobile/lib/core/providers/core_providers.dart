import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/api_client.dart';
import '../network/token_storage.dart';
import '../network/ws_client.dart';

/// Singleton token storage.
final tokenStorageProvider = Provider<TokenStorage>((ref) {
  return TokenStorage();
});

/// Singleton API client with JWT interceptor.
final apiClientProvider = Provider<ApiClient>((ref) {
  final tokenStorage = ref.watch(tokenStorageProvider);
  return ApiClient(tokenStorage: tokenStorage);
});

/// Singleton WebSocket client.
final wsClientProvider = Provider<WsClient>((ref) {
  final tokenStorage = ref.watch(tokenStorageProvider);
  return WsClient(tokenStorage: tokenStorage);
});
