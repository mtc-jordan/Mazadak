import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers/auth_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../l10n/app_localizations.dart';

/// Phone registration — step 1 of auth flow.
///
/// Country picker (GCC defaults), auto-formatted phone input with live
/// validation, and CTA that POSTs to /api/v1/auth/register then navigates
/// to OTP verification.
class PhoneRegistrationScreen extends ConsumerStatefulWidget {
  const PhoneRegistrationScreen({super.key});

  @override
  ConsumerState<PhoneRegistrationScreen> createState() =>
      _PhoneRegistrationScreenState();
}

class _PhoneRegistrationScreenState extends ConsumerState<PhoneRegistrationScreen> {
  final _phoneController = TextEditingController();
  final _focusNode = FocusNode();

  _Country _selectedCountry = _countries.first; // Jordan
  bool _isLoading = false;
  bool _hasTouched = false; // show error only after user starts typing

  static const _fog = Color(0xFFF5F2EC);

  @override
  void initState() {
    super.initState();
    _phoneController.addListener(_onPhoneChanged);
  }

  void _onPhoneChanged() {
    if (!_hasTouched && _phoneController.text.isNotEmpty) {
      _hasTouched = true;
    }
    setState(() {});
  }

  @override
  void dispose() {
    _phoneController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  // ── Validation ──────────────────────────────────────────────────

  String get _rawDigits =>
      _phoneController.text.replaceAll(RegExp(r'\D'), '');

  bool get _isValid => _selectedCountry.validate(_rawDigits);

  String? get _errorText {
    if (!_hasTouched || _rawDigits.isEmpty) return null;
    if (!_isValid) return _selectedCountry.errorHint;
    return null;
  }

  // ── Auto-format ─────────────────────────────────────────────────

  String _formatPhone(String raw) => _selectedCountry.format(raw);

  // ── Actions ─────────────────────────────────────────────────────

  Future<void> _onContinue() async {
    if (!_isValid || _isLoading) return;
    HapticFeedback.mediumImpact();

    setState(() => _isLoading = true);

    // Strip leading 0 (local trunk prefix) for E.164 format
    final digits = _rawDigits.startsWith('0')
        ? _rawDigits.substring(1)
        : _rawDigits;
    final phone = '${_selectedCountry.dialCode}$digits';

    try {
      await ref.read(authProvider.notifier).requestOtp(phone);

      if (!mounted) return;
      setState(() => _isLoading = false);

      context.push(AppRoutes.otp, extra: phone);
    } on DioException catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);

      if (e.response?.statusCode == 429) {
        _showError(S.of(context).authTooManyAttempts);
      } else {
        _showError(S.of(context).authConnectionError);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _showError(S.of(context).authGenericError);
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message, textAlign: TextAlign.center),
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.ember,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        duration: const Duration(seconds: 4),
      ),
    );
  }

  void _openCountryPicker() {
    showModalBottomSheet<_Country>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => _CountryPickerSheet(
        selected: _selectedCountry,
        onSelect: (c) {
          setState(() {
            _selectedCountry = c;
            _phoneController.clear();
            _hasTouched = false;
          });
        },
      ),
    );
  }

  // ── Build ───────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final bottomPadding = MediaQuery.of(context).padding.bottom;

    return Scaffold(
      backgroundColor: _fog,
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded, color: AppColors.navy),
          onPressed: () => context.pop(),
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── Progress dots ────────────────────────────────────
            _ProgressDots(current: 0, total: 3),
            const SizedBox(height: 32),

            // ── Headline ─────────────────────────────────────────
            const Text(
              "What's your number?",
              textDirection: TextDirection.ltr,
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 26,
                fontWeight: FontWeight.w800,
                color: AppColors.navy,
                height: 1.2,
              ),
            ),
            const SizedBox(height: 8),
            const Text(
              "We'll send a verification code · سنرسل رمز التحقق",
              textDirection: TextDirection.ltr,
              style: TextStyle(
                fontSize: 13,
                color: AppColors.mist,
                height: 1.4,
              ),
            ),
            const SizedBox(height: 28),

            // ── Country picker ───────────────────────────────────
            Directionality(
              textDirection: TextDirection.ltr,
              child: GestureDetector(
                onTap: _openCountryPicker,
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(color: AppColors.sand, width: 0.5),
                  ),
                  child: Row(
                    children: [
                      Text(
                        _selectedCountry.flag,
                        style: const TextStyle(fontSize: 22),
                      ),
                      const SizedBox(width: 10),
                      Text(
                        _selectedCountry.name,
                        style: const TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: AppColors.navy,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Text(
                        _selectedCountry.dialCode,
                        style: const TextStyle(
                          fontSize: 14,
                          color: AppColors.mist,
                        ),
                      ),
                      const Spacer(),
                      const Icon(
                        Icons.keyboard_arrow_down_rounded,
                        color: AppColors.mist,
                        size: 22,
                      ),
                    ],
                  ),
                ),
              ),
            ),
            const SizedBox(height: 14),

            // ── Phone input (always LTR — numbers are universal) ─
            Directionality(
              textDirection: TextDirection.ltr,
              child: AnimatedBuilder(
              animation: _focusNode,
              builder: (_, child) {
                final focused = _focusNode.hasFocus;
                final hasError = _errorText != null;
                final borderColor = hasError
                    ? AppColors.ember
                    : focused
                        ? AppColors.navy
                        : AppColors.sand;
                final borderWidth = focused || hasError ? 1.5 : 0.5;

                return Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(14),
                        border: Border.all(
                          color: borderColor,
                          width: borderWidth,
                        ),
                      ),
                      child: child,
                    ),
                    if (hasError) ...[
                      const SizedBox(height: 6),
                      Text(
                        _errorText!,
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.ember,
                        ),
                      ),
                    ],
                  ],
                );
              },
              child: TextField(
                controller: _phoneController,
                focusNode: _focusNode,
                keyboardType: TextInputType.phone,
                style: const TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.w600,
                  color: AppColors.navy,
                  letterSpacing: 0.5,
                ),
                inputFormatters: [
                  FilteringTextInputFormatter.digitsOnly,
                  _PhoneFormatter(_selectedCountry),
                ],
                decoration: InputDecoration(
                  border: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 16,
                  ),
                  prefixIcon: Padding(
                    padding: const EdgeInsetsDirectional.only(start: 14, end: 8),
                    child: Text(
                      _selectedCountry.dialCode,
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                      ),
                    ),
                  ),
                  prefixIconConstraints: const BoxConstraints(minWidth: 0),
                  hintText: _selectedCountry.placeholder,
                  hintStyle: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w400,
                    color: AppColors.mist.withOpacity(0.5),
                  ),
                  suffixIcon: _phoneController.text.isNotEmpty
                      ? IconButton(
                          icon: const Icon(Icons.close_rounded, size: 18),
                          color: AppColors.mist,
                          onPressed: () {
                            _phoneController.clear();
                            _hasTouched = false;
                          },
                        )
                      : null,
                ),
              ),
            ),
            ),

            const Spacer(),

            // ── CTA Button ───────────────────────────────────────
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              curve: Curves.easeOut,
              width: double.infinity,
              height: 54,
              child: ElevatedButton(
                onPressed: _isValid ? _onContinue : null,
                style: ElevatedButton.styleFrom(
                  backgroundColor: AppColors.navy,
                  disabledBackgroundColor: AppColors.navy.withOpacity(0.4),
                  foregroundColor: Colors.white,
                  disabledForegroundColor: Colors.white.withOpacity(0.6),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14),
                  ),
                  elevation: 0,
                  textStyle: const TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    height: 1,
                  ),
                ),
                child: _isLoading
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2.5,
                          color: Colors.white,
                        ),
                      )
                    : Text(S.of(context).authContinue),
              ),
            ),
            const SizedBox(height: 14),

            // ── Legal text ───────────────────────────────────────
            const Center(
              child: Text(
                'By continuing you agree to our Terms & Privacy Policy',
                style: TextStyle(fontSize: 10, color: AppColors.mist),
                textAlign: TextAlign.center,
              ),
            ),
            SizedBox(height: bottomPadding + 12),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Progress dots
// ═══════════════════════════════════════════════════════════════════

class _ProgressDots extends StatelessWidget {
  const _ProgressDots({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(total, (i) {
        return Container(
          width: 8,
          height: 8,
          margin: EdgeInsetsDirectional.only(end: i < total - 1 ? 8 : 0),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: i == current ? AppColors.gold : AppColors.mist.withOpacity(0.3),
          ),
        );
      }),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Country model + data
// ═══════════════════════════════════════════════════════════════════

class _Country {
  const _Country({
    required this.name,
    required this.flag,
    required this.dialCode,
    required this.minDigits,
    required this.maxDigits,
    required this.placeholder,
    this.errorHint = 'Invalid phone number',
    this.formatPattern,
  });

  final String name;
  final String flag;
  final String dialCode;
  final int minDigits;
  final int maxDigits;
  final String placeholder;
  final String errorHint;
  /// e.g. "### ### ####" where # = digit slot
  final String? formatPattern;

  bool validate(String digits) =>
      digits.length >= minDigits && digits.length <= maxDigits;

  String format(String digits) {
    final p = formatPattern;
    if (p == null) return digits;
    final buf = StringBuffer();
    var di = 0;
    for (var i = 0; i < p.length && di < digits.length; i++) {
      if (p[i] == '#') {
        buf.write(digits[di++]);
      } else {
        buf.write(p[i]);
      }
    }
    return buf.toString();
  }
}

const _countries = [
  _Country(
    name: 'Jordan',
    flag: '🇯🇴',
    dialCode: '+962',
    minDigits: 9,
    maxDigits: 10,
    placeholder: '07XX XXX XXX',
    errorHint: 'Enter a valid Jordanian number (07XXXXXXXX)',
    formatPattern: '#### ### ###',
  ),
  _Country(
    name: 'Saudi Arabia',
    flag: '🇸🇦',
    dialCode: '+966',
    minDigits: 9,
    maxDigits: 9,
    placeholder: '5XX XXX XXX',
    errorHint: 'Enter a valid Saudi number',
    formatPattern: '### ### ###',
  ),
  _Country(
    name: 'UAE',
    flag: '🇦🇪',
    dialCode: '+971',
    minDigits: 9,
    maxDigits: 9,
    placeholder: '5XX XXX XXXX',
    errorHint: 'Enter a valid UAE number',
    formatPattern: '### ### ####',
  ),
  _Country(
    name: 'Kuwait',
    flag: '🇰🇼',
    dialCode: '+965',
    minDigits: 8,
    maxDigits: 8,
    placeholder: 'XXXX XXXX',
    errorHint: 'Enter a valid Kuwaiti number',
    formatPattern: '#### ####',
  ),
  _Country(
    name: 'Qatar',
    flag: '🇶🇦',
    dialCode: '+974',
    minDigits: 8,
    maxDigits: 8,
    placeholder: 'XXXX XXXX',
    errorHint: 'Enter a valid Qatari number',
    formatPattern: '#### ####',
  ),
  _Country(
    name: 'Bahrain',
    flag: '🇧🇭',
    dialCode: '+973',
    minDigits: 8,
    maxDigits: 8,
    placeholder: 'XXXX XXXX',
    errorHint: 'Enter a valid Bahraini number',
    formatPattern: '#### ####',
  ),
  _Country(
    name: 'Egypt',
    flag: '🇪🇬',
    dialCode: '+20',
    minDigits: 10,
    maxDigits: 11,
    placeholder: '01X XXXX XXXX',
    errorHint: 'Enter a valid Egyptian number',
    formatPattern: '### #### ####',
  ),
];

// ═══════════════════════════════════════════════════════════════════
// Phone number formatter (TextInputFormatter)
// ═══════════════════════════════════════════════════════════════════

class _PhoneFormatter extends TextInputFormatter {
  _PhoneFormatter(this.country);
  final _Country country;

  @override
  TextEditingValue formatEditUpdate(
    TextEditingValue oldValue,
    TextEditingValue newValue,
  ) {
    final digits = newValue.text.replaceAll(RegExp(r'\D'), '');
    final capped = digits.length > country.maxDigits
        ? digits.substring(0, country.maxDigits)
        : digits;

    final formatted = country.format(capped);
    return TextEditingValue(
      text: formatted,
      selection: TextSelection.collapsed(offset: formatted.length),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Country picker bottom sheet
// ═══════════════════════════════════════════════════════════════════

class _CountryPickerSheet extends StatefulWidget {
  const _CountryPickerSheet({
    required this.selected,
    required this.onSelect,
  });

  final _Country selected;
  final ValueChanged<_Country> onSelect;

  @override
  State<_CountryPickerSheet> createState() => _CountryPickerSheetState();
}

class _CountryPickerSheetState extends State<_CountryPickerSheet> {
  String _query = '';

  List<_Country> get _filtered => _query.isEmpty
      ? _countries
      : _countries
          .where((c) =>
              c.name.toLowerCase().contains(_query.toLowerCase()) ||
              c.dialCode.contains(_query))
          .toList();

  @override
  Widget build(BuildContext context) {
    final bottomPadding = MediaQuery.of(context).padding.bottom;

    return Padding(
      padding: EdgeInsets.only(bottom: bottomPadding),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(height: 12),
          Container(
            width: 36,
            height: 4,
            decoration: BoxDecoration(
              color: AppColors.sand,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: TextField(
              autofocus: true,
              decoration: InputDecoration(
                hintText: S.of(context).authSearchCountry,
                hintStyle: const TextStyle(
                  fontSize: 14,
                  color: AppColors.mist,
                ),
                prefixIcon: const Icon(
                  Icons.search_rounded,
                  color: AppColors.mist,
                  size: 20,
                ),
                filled: true,
                fillColor: const Color(0xFFF5F2EC),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 12,
                ),
              ),
              onChanged: (v) => setState(() => _query = v),
            ),
          ),
          Flexible(
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: _filtered.length,
              itemBuilder: (_, i) {
                final c = _filtered[i];
                final isSelected = c.dialCode == widget.selected.dialCode;
                return InkWell(
                  onTap: () {
                    widget.onSelect(c);
                    Navigator.pop(context);
                  },
                  child: Container(
                    height: 48,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    color: isSelected
                        ? AppColors.cream.withOpacity(0.5)
                        : Colors.transparent,
                    child: Row(
                      children: [
                        Text(c.flag, style: const TextStyle(fontSize: 22)),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            c.name,
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: isSelected
                                  ? FontWeight.w700
                                  : FontWeight.w500,
                              color: AppColors.navy,
                            ),
                          ),
                        ),
                        Text(
                          c.dialCode,
                          style: const TextStyle(
                            fontSize: 13,
                            color: AppColors.mist,
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}
