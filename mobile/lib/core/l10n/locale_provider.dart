import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Supported locales.
const supportedLocales = [
  Locale('ar', 'JO'), // Arabic — Jordan (default)
  Locale('en', 'US'), // English — US
];

/// Default locale (Arabic).
const defaultLocale = Locale('ar', 'JO');

/// Persisted locale preference. Defaults to ar_JO.
final localeProvider = StateNotifierProvider<LocaleNotifier, Locale>((ref) {
  return LocaleNotifier();
});

class LocaleNotifier extends StateNotifier<Locale> {
  LocaleNotifier() : super(defaultLocale) {
    _load();
  }

  static const _key = 'mzadak_locale';

  Future<void> _load() async {
    final prefs = await SharedPreferences.getInstance();
    final code = prefs.getString(_key);
    if (code != null) {
      final parts = code.split('_');
      state = Locale(parts[0], parts.length > 1 ? parts[1] : null);
    }
  }

  Future<void> setLocale(Locale locale) async {
    state = locale;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _key,
      locale.countryCode != null
          ? '${locale.languageCode}_${locale.countryCode}'
          : locale.languageCode,
    );
  }

  void toggleLocale() {
    if (state.languageCode == 'ar') {
      setLocale(const Locale('en', 'US'));
    } else {
      setLocale(const Locale('ar', 'JO'));
    }
  }

  /// Whether the current locale is RTL.
  bool get isRtl => state.languageCode == 'ar';
}
