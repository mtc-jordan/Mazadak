import 'package:intl/intl.dart';

/// Arabic numeral formatting utilities for MZADAK.
///
/// Formats numbers using Eastern Arabic numerals (٠١٢٣٤٥٦٧٨٩)
/// and handles JOD 3-decimal currency formatting.
abstract final class ArabicNumerals {
  /// Format a number with Arabic-Indic digits for ar_JO locale.
  ///
  /// Example: `formatNumber(1234)` → `"١٬٢٣٤"`
  static String formatNumber(num value, {String locale = 'ar_JO'}) {
    return NumberFormat('#,##0', locale).format(value);
  }

  /// Format a decimal number with Arabic-Indic digits.
  ///
  /// Example: `formatDecimal(1234.567, 3)` → `"١٬٢٣٤٫٥٦٧"`
  static String formatDecimal(
    num value, {
    int decimalDigits = 2,
    String locale = 'ar_JO',
  }) {
    return NumberFormat('#,##0.${'0' * decimalDigits}', locale).format(value);
  }

  /// Format currency amount with symbol.
  ///
  /// JOD/KWD/BHD/OMR use 3 decimal places; others use 2.
  /// Example: `formatCurrency(350.500, 'JOD')` → `"٣٥٠٫٥٠٠ د.أ"`
  static String formatCurrency(
    num amount,
    String currencyCode, {
    String locale = 'ar_JO',
  }) {
    final decimals = _threeDecimalCurrencies.contains(currencyCode) ? 3 : 2;
    final formatted = formatDecimal(amount, decimalDigits: decimals, locale: locale);

    final symbol = _currencySymbols[currencyCode] ?? currencyCode;
    return '$formatted $symbol';
  }

  /// Format currency in English locale.
  static String formatCurrencyEn(num amount, String currencyCode) {
    final decimals = _threeDecimalCurrencies.contains(currencyCode) ? 3 : 2;
    final formatted = NumberFormat(
      '#,##0.${'0' * decimals}',
      'en_US',
    ).format(amount);
    return '$formatted $currencyCode';
  }

  /// Format a percentage.
  ///
  /// Example: `formatPercent(0.856)` → `"٨٥٫٦٪"`
  static String formatPercent(double value, {String locale = 'ar_JO'}) {
    return NumberFormat.percentPattern(locale).format(value);
  }

  /// Compact number format (e.g., 1.2K, 3.5M).
  ///
  /// Example: `formatCompact(15000)` → `"١٥ ألف"`
  static String formatCompact(num value, {String locale = 'ar_JO'}) {
    return NumberFormat.compact(locale: locale).format(value);
  }

  // ── Internals ─────────────────────────────────────────────────

  static const _threeDecimalCurrencies = {'JOD', 'KWD', 'BHD', 'OMR'};

  static const _currencySymbols = {
    'JOD': 'د.أ',
    'SAR': 'ر.س',
    'AED': 'د.إ',
    'KWD': 'د.ك',
    'BHD': 'د.ب',
    'OMR': 'ر.ع',
    'QAR': 'ر.ق',
    'USD': '\$',
    'EUR': '€',
  };
}
