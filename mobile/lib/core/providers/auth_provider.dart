import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../network/api_client.dart';
import '../network/token_storage.dart';
import 'core_providers.dart';

/// Authentication state.
enum AuthStatus { unknown, authenticated, unauthenticated }

class AuthState {
  const AuthState({
    this.status = AuthStatus.unknown,
    this.userId,
    this.phone,
    this.fullNameAr,
    this.role,
    this.kycStatus,
    this.isLoading = false,
    this.error,
  });

  final AuthStatus status;
  final String? userId;
  final String? phone;
  final String? fullNameAr;
  final String? role;
  final String? kycStatus;
  final bool isLoading;
  final String? error;

  AuthState copyWith({
    AuthStatus? status,
    String? userId,
    String? phone,
    String? fullNameAr,
    String? role,
    String? kycStatus,
    bool? isLoading,
    String? error,
  }) => AuthState(
        status: status ?? this.status,
        userId: userId ?? this.userId,
        phone: phone ?? this.phone,
        fullNameAr: fullNameAr ?? this.fullNameAr,
        role: role ?? this.role,
        kycStatus: kycStatus ?? this.kycStatus,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

/// Auth provider — SDD §7.1 authProvider.
///
/// Manages OTP login flow, token persistence, and session state.
final authProvider = StateNotifierProvider<AuthNotifier, AuthState>((ref) {
  return AuthNotifier(
    api: ref.watch(apiClientProvider),
    tokenStorage: ref.watch(tokenStorageProvider),
  );
});

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier({required this.api, required this.tokenStorage})
      : super(const AuthState()) {
    _checkExistingSession();
  }

  final ApiClient api;
  final TokenStorage tokenStorage;

  Future<void> _checkExistingSession() async {
    final hasTokens = await tokenStorage.hasTokens;
    if (hasTokens) {
      try {
        final resp = await api.get('/auth/me');
        final data = resp.data as Map<String, dynamic>;
        state = AuthState(
          status: AuthStatus.authenticated,
          userId: data['id'] as String?,
          phone: data['phone'] as String?,
          fullNameAr: data['full_name_ar'] as String?,
          role: data['role'] as String?,
          kycStatus: data['kyc_status'] as String?,
        );
      } catch (_) {
        await tokenStorage.clearTokens();
        state = const AuthState(status: AuthStatus.unauthenticated);
      }
    } else {
      state = const AuthState(status: AuthStatus.unauthenticated);
    }
  }

  /// Step 1: Request OTP for phone number.
  Future<void> requestOtp(String phone) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      await api.post('/auth/otp/request', data: {'phone': phone});
      state = state.copyWith(isLoading: false, phone: phone);
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  /// Step 2: Verify OTP and receive JWT tokens.
  Future<bool> verifyOtp(String phone, String code) async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final resp = await api.post('/auth/otp/verify', data: {
        'phone': phone,
        'code': code,
      });
      final data = resp.data as Map<String, dynamic>;

      await tokenStorage.saveTokens(
        accessToken: data['access_token'] as String,
        refreshToken: data['refresh_token'] as String,
      );

      final user = data['user'] as Map<String, dynamic>;
      state = AuthState(
        status: AuthStatus.authenticated,
        userId: user['id'] as String?,
        phone: user['phone'] as String?,
        fullNameAr: user['full_name_ar'] as String?,
        role: user['role'] as String?,
        kycStatus: user['kyc_status'] as String?,
      );
      return true;
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
      return false;
    }
  }

  /// Log out — clear tokens and reset state.
  Future<void> logout() async {
    await tokenStorage.clearTokens();
    state = const AuthState(status: AuthStatus.unauthenticated);
  }
}
