import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'token_storage.dart';

/// API base URL — override via --dart-define=API_BASE_URL=...
const _defaultBaseUrl = 'http://10.0.2.2:8000/api/v1'; // Android emulator

String get _baseUrl =>
    const String.fromEnvironment('API_BASE_URL', defaultValue: _defaultBaseUrl);

/// Singleton Dio-based API client with:
/// - Automatic Authorization header injection
/// - Silent JWT refresh on 401
/// - Request/response logging in debug mode
class ApiClient {
  ApiClient({required this.tokenStorage}) {
    _dio = Dio(BaseOptions(
      baseUrl: _baseUrl,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 15),
      headers: {
        HttpHeaders.contentTypeHeader: 'application/json',
        HttpHeaders.acceptHeader: 'application/json',
      },
    ));

    _dio.interceptors.add(_AuthInterceptor(tokenStorage, _dio));

    if (kDebugMode) {
      _dio.interceptors.add(LogInterceptor(
        requestBody: true,
        responseBody: true,
        logPrint: (obj) => debugPrint('[API] $obj'),
      ));
    }
  }

  final TokenStorage tokenStorage;
  late final Dio _dio;

  Dio get dio => _dio;

  // ── Convenience methods ─────────────────────────────────────────

  Future<Response<T>> get<T>(
    String path, {
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) => _dio.get<T>(path, queryParameters: queryParameters, options: options);

  Future<Response<T>> post<T>(
    String path, {
    Object? data,
    Options? options,
  }) => _dio.post<T>(path, data: data, options: options);

  Future<Response<T>> put<T>(
    String path, {
    Object? data,
    Options? options,
  }) => _dio.put<T>(path, data: data, options: options);

  Future<Response<T>> patch<T>(
    String path, {
    Object? data,
    Options? options,
  }) => _dio.patch<T>(path, data: data, options: options);

  Future<Response<T>> delete<T>(
    String path, {
    Object? data,
    Options? options,
  }) => _dio.delete<T>(path, data: data, options: options);
}

/// Interceptor that:
/// 1. Attaches Bearer token to every request
/// 2. On 401, silently refreshes the token and retries the original request
/// 3. On refresh failure, clears tokens (forces re-login)
class _AuthInterceptor extends Interceptor {
  _AuthInterceptor(this._storage, this._dio);

  final TokenStorage _storage;
  final Dio _dio;
  bool _isRefreshing = false;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final token = await _storage.accessToken;
    if (token != null) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }

  @override
  Future<void> onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (err.response?.statusCode != 401 || _isRefreshing) {
      return handler.next(err);
    }

    _isRefreshing = true;
    try {
      final refreshToken = await _storage.refreshToken;
      if (refreshToken == null) {
        await _storage.clearTokens();
        return handler.next(err);
      }

      // Call refresh endpoint (no auth header — uses refresh token in body)
      final refreshDio = Dio(BaseOptions(baseUrl: _baseUrl));
      final response = await refreshDio.post(
        '/auth/refresh',
        data: {'refresh_token': refreshToken},
      );

      final newAccess  = response.data['access_token'] as String;
      final newRefresh = response.data['refresh_token'] as String;
      await _storage.saveTokens(
        accessToken: newAccess,
        refreshToken: newRefresh,
      );

      // Retry original request with new token
      final opts = err.requestOptions;
      opts.headers['Authorization'] = 'Bearer $newAccess';
      final retryResponse = await _dio.fetch(opts);
      return handler.resolve(retryResponse);
    } on DioException {
      // Refresh failed — force logout
      await _storage.clearTokens();
      return handler.next(err);
    } finally {
      _isRefreshing = false;
    }
  }
}
