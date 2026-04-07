import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Secure JWT token storage backed by flutter_secure_storage.
///
/// - iOS: Keychain
/// - Android: AES-encrypted SharedPreferences (EncryptedSharedPreferences)
class TokenStorage {
  TokenStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _accessKey  = 'mzadak_access_token';
  static const _refreshKey = 'mzadak_refresh_token';

  Future<String?> get accessToken  => _storage.read(key: _accessKey);
  Future<String?> get refreshToken => _storage.read(key: _refreshKey);

  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    await Future.wait([
      _storage.write(key: _accessKey, value: accessToken),
      _storage.write(key: _refreshKey, value: refreshToken),
    ]);
  }

  Future<void> clearTokens() async {
    await Future.wait([
      _storage.delete(key: _accessKey),
      _storage.delete(key: _refreshKey),
    ]);
  }

  Future<bool> get hasTokens async => (await accessToken) != null;
}
