import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/providers/auth_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../l10n/app_localizations.dart';

/// OTP verification — step 2 of auth flow.
///
/// 6-box OTP input with auto-advance, paste handling, shake on error,
/// emerald spring on success, resend countdown timer, and auto-submit.
class OtpVerificationScreen extends ConsumerStatefulWidget {
  const OtpVerificationScreen({super.key, required this.phoneNumber});

  /// Full international number, e.g. "+962790123456".
  final String phoneNumber;

  @override
  ConsumerState<OtpVerificationScreen> createState() =>
      _OtpVerificationScreenState();
}

class _OtpVerificationScreenState extends ConsumerState<OtpVerificationScreen>
    with TickerProviderStateMixin {
  static const _codeLength = 6;
  static const _fog = Color(0xFFF5F2EC);

  // ── Per-box controllers & focus nodes ───────────────────────────
  late final List<TextEditingController> _controllers;
  late final List<FocusNode> _focusNodes;

  // ── Shake animation: ±6px, 3 cycles, 300ms ─────────────────────
  late final AnimationController _shakeController;
  late final Animation<double> _shakeOffset;

  // ── Success animation: scale 1.05 → 1.0 spring ─────────────────
  late final AnimationController _successController;
  late final Animation<double> _successScale;

  // ── Resend countdown ────────────────────────────────────────────
  Timer? _resendTimer;
  int _secondsLeft = 60;

  // ── State ───────────────────────────────────────────────────────
  bool _isVerifying = false;
  bool _isSuccess = false;
  String? _errorMessage;

  @override
  void initState() {
    super.initState();

    _controllers = List.generate(_codeLength, (_) => TextEditingController());
    _focusNodes = List.generate(_codeLength, (_) => FocusNode());

    // Shake: 3 cycles of ±6px in 300ms via TweenSequence
    _shakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _shakeOffset = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0, end: -6), weight: 1),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: 6, end: -6), weight: 2),
      TweenSequenceItem(tween: Tween(begin: -6, end: 0), weight: 1),
    ]).animate(CurvedAnimation(
      parent: _shakeController,
      curve: Curves.easeInOut,
    ));

    // Success: scale up then back down
    _successController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _successScale = TweenSequence<double>([
      TweenSequenceItem(
        tween: Tween(begin: 1.0, end: 1.05)
            .chain(CurveTween(curve: Curves.easeOut)),
        weight: 1,
      ),
      TweenSequenceItem(
        tween: Tween(begin: 1.05, end: 1.0)
            .chain(CurveTween(curve: Curves.elasticOut)),
        weight: 2,
      ),
    ]).animate(_successController);

    _startResendTimer();

    // Auto-focus first box
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _focusNodes[0].requestFocus();
    });
  }

  @override
  void dispose() {
    _resendTimer?.cancel();
    _shakeController.dispose();
    _successController.dispose();
    for (final c in _controllers) {
      c.dispose();
    }
    for (final f in _focusNodes) {
      f.dispose();
    }
    super.dispose();
  }

  // ── Timer ───────────────────────────────────────────────────────

  void _startResendTimer() {
    _secondsLeft = 60;
    _resendTimer?.cancel();
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      setState(() {
        _secondsLeft--;
        if (_secondsLeft <= 0) t.cancel();
      });
    });
  }

  // ── Input handling ──────────────────────────────────────────────

  void _onDigitChanged(int index, String value) {
    // Clear error state on new input
    if (_errorMessage != null) {
      setState(() => _errorMessage = null);
    }

    if (value.length > 1) {
      // Paste handling: distribute digits across boxes
      final digits = value.replaceAll(RegExp(r'\D'), '');
      if (digits.length >= _codeLength) {
        _pasteCode(digits.substring(0, _codeLength));
        return;
      }
      // Single overflow — take last char
      _controllers[index].text = value[value.length - 1];
    }

    if (value.isNotEmpty && index < _codeLength - 1) {
      // Auto-advance
      _focusNodes[index + 1].requestFocus();
    }

    // Check if all filled → auto-submit
    if (_fullCode.length == _codeLength) {
      _verifyOtp();
    }
  }

  void _onKeyEvent(int index, KeyEvent event) {
    if (event is! KeyDownEvent) return;
    if (event.logicalKey == LogicalKeyboardKey.backspace &&
        _controllers[index].text.isEmpty &&
        index > 0) {
      // Auto-backspace to previous box
      _controllers[index - 1].clear();
      _focusNodes[index - 1].requestFocus();
    }
  }

  void _pasteCode(String code) {
    for (var i = 0; i < _codeLength; i++) {
      _controllers[i].text = code[i];
    }
    _focusNodes[_codeLength - 1].requestFocus();
    _verifyOtp();
  }

  String get _fullCode =>
      _controllers.map((c) => c.text).join().replaceAll(RegExp(r'\D'), '');

  // ── Verification ────────────────────────────────────────────────

  Future<void> _verifyOtp() async {
    if (_isVerifying || _fullCode.length != _codeLength) return;

    setState(() {
      _isVerifying = true;
      _errorMessage = null;
    });

    try {
      final success = await ref
          .read(authProvider.notifier)
          .verifyOtp(widget.phoneNumber, _fullCode);

      if (!mounted) return;

      if (success) {
        _onSuccess();
      } else {
        _onError('Invalid code · رمز غير صحيح');
      }
    } on DioException catch (e) {
      if (!mounted) return;
      final status = e.response?.statusCode;
      if (status == 400) {
        _onError('Invalid code · رمز غير صحيح');
      } else if (status == 429) {
        _onError('Too many attempts · حاول لاحقاً');
      } else {
        _onError('Connection error · خطأ في الاتصال');
      }
    } catch (_) {
      if (!mounted) return;
      _onError('Something went wrong · حدث خطأ');
    }
  }

  void _onSuccess() {
    setState(() {
      _isVerifying = false;
      _isSuccess = true;
    });
    HapticFeedback.mediumImpact();
    _successController.forward();

    // Navigate after animation settles
    Future.delayed(const Duration(milliseconds: 300), () {
      if (!mounted) return;

      final authState = ref.read(authProvider);
      final kyc = authState.kycStatus;

      // New user or KYC not started → KYC flow
      if (kyc == null || kyc == 'not_started' || kyc == 'pending') {
        context.go(AppRoutes.kyc);
      } else {
        // KYC verified / any other status → Home
        context.go(AppRoutes.home);
      }
    });
  }

  void _onError(String message) {
    setState(() {
      _isVerifying = false;
      _errorMessage = message;
    });
    HapticFeedback.heavyImpact();
    _shakeController.forward(from: 0);

    // Clear all boxes after shake
    Future.delayed(const Duration(milliseconds: 350), () {
      if (!mounted) return;
      for (final c in _controllers) {
        c.clear();
      }
      _focusNodes[0].requestFocus();
    });
  }

  // ── Resend ──────────────────────────────────────────────────────

  Future<void> _resendCode() async {
    if (_secondsLeft > 0) return;

    try {
      await ref.read(authProvider.notifier).requestOtp(widget.phoneNumber);
    } catch (_) {
      // Silently fail — timer restarts regardless
    }
    if (!mounted) return;

    _startResendTimer();

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(S.of(context).authCodeResent),
        backgroundColor: AppColors.navy,
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        duration: const Duration(seconds: 2),
      ),
    );
  }

  // ── Formatted phone for display ─────────────────────────────────

  String get _displayPhone {
    final p = widget.phoneNumber;
    // Mask middle digits: +962 7X XXX XXXX
    if (p.length >= 8) {
      final prefix = p.substring(0, p.length > 6 ? 6 : 4);
      final suffix = p.substring(p.length - 4);
      final masked = 'X' * (p.length - prefix.length - suffix.length);
      return '$prefix $masked $suffix'.replaceAllMapped(
        RegExp(r'(.{3,4})(?=.)'),
        (m) => '${m[0]} ',
      ).trim();
    }
    return p;
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
            // ── Progress dots (step 2 of 3) ──────────────────────
            _ProgressDots(current: 1, total: 3),
            const SizedBox(height: 32),

            // ── Header ───────────────────────────────────────────
            const Text(
              'Verify your number',
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
            Text.rich(
              TextSpan(
                text: 'We sent a 6-digit code to ',
                style: const TextStyle(
                  fontSize: 13,
                  color: AppColors.mist,
                  height: 1.4,
                ),
                children: [
                  TextSpan(
                    text: widget.phoneNumber,
                    style: const TextStyle(
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                ],
              ),
              textDirection: TextDirection.ltr,
            ),
            const SizedBox(height: 4),
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: GestureDetector(
                onTap: () => context.pop(),
                child: const Text(
                  'Change number',
                  style: TextStyle(
                    fontSize: 12,
                    color: AppColors.gold,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 36),

            // ── OTP boxes (always LTR — digits fill left to right) ─
            Directionality(
              textDirection: TextDirection.ltr,
              child: AnimatedBuilder(
                animation: Listenable.merge([_shakeController, _successController]),
                builder: (_, child) {
                  final dx = _shakeController.isAnimating
                      ? _shakeOffset.value
                      : 0.0;
                  final scale = _successController.isAnimating ||
                          _successController.isCompleted
                      ? _successScale.value
                      : 1.0;

                  return Transform.translate(
                    offset: Offset(dx, 0),
                    child: Transform.scale(
                      scale: scale,
                      child: child,
                    ),
                  );
                },
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: List.generate(_codeLength, (i) {
                    return Padding(
                      padding: EdgeInsets.only(
                        right: i < _codeLength - 1 ? 8 : 0,
                      ),
                      child: _OtpBox(
                        controller: _controllers[i],
                        focusNode: _focusNodes[i],
                        isSuccess: _isSuccess,
                        hasError: _errorMessage != null,
                        onChanged: (v) => _onDigitChanged(i, v),
                        onKeyEvent: (e) => _onKeyEvent(i, e),
                      ),
                    );
                  }),
                ),
              ),
            ),

            // ── Loading indicator ────────────────────────────────
            const SizedBox(height: 4),
            SizedBox(
              height: 2,
              child: _isVerifying
                  ? LinearProgressIndicator(
                      backgroundColor: AppColors.sand,
                      color: AppColors.gold,
                      minHeight: 2,
                    )
                  : const SizedBox.shrink(),
            ),

            // ── Error message ────────────────────────────────────
            if (_errorMessage != null) ...[
              const SizedBox(height: 12),
              Center(
                child: Text(
                  _errorMessage!,
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.ember,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
            const SizedBox(height: 28),

            // ── Timer / Resend ───────────────────────────────────
            Center(
              child: _secondsLeft > 0
                  ? Text(
                      'Resend code in 0:${_secondsLeft.toString().padLeft(2, '0')}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.mist,
                      ),
                    )
                  : GestureDetector(
                      onTap: _resendCode,
                      child: const Text.rich(
                        TextSpan(
                          text: "Didn't receive it? ",
                          style: TextStyle(
                            fontSize: 12,
                            color: AppColors.mist,
                          ),
                          children: [
                            TextSpan(
                              text: 'Resend · أعد الإرسال',
                              style: TextStyle(
                                color: AppColors.gold,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
            ),

            const Spacer(),

            // ── Security note ────────────────────────────────────
            Center(
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.schedule_rounded,
                    size: 12,
                    color: AppColors.mist.withOpacity(0.7),
                  ),
                  const SizedBox(width: 4),
                  Text(
                    'This code expires in 5 minutes',
                    style: TextStyle(
                      fontSize: 10,
                      color: AppColors.mist.withOpacity(0.7),
                    ),
                  ),
                ],
              ),
            ),
            SizedBox(height: bottomPadding + 16),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Individual OTP box
// ═══════════════════════════════════════════════════════════════════

class _OtpBox extends StatelessWidget {
  const _OtpBox({
    required this.controller,
    required this.focusNode,
    required this.isSuccess,
    required this.hasError,
    required this.onChanged,
    required this.onKeyEvent,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool isSuccess;
  final bool hasError;
  final ValueChanged<String> onChanged;
  final ValueChanged<KeyEvent> onKeyEvent;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: focusNode,
      builder: (_, __) {
        final focused = focusNode.hasFocus;
        final filled = controller.text.isNotEmpty;

        Color borderColor;
        Color bgColor;

        if (isSuccess) {
          borderColor = AppColors.emerald;
          bgColor = AppColors.emerald.withOpacity(0.08);
        } else if (hasError) {
          borderColor = AppColors.ember;
          bgColor = Colors.white;
        } else if (focused) {
          borderColor = AppColors.navy;
          bgColor = Colors.white;
        } else if (filled) {
          borderColor = AppColors.navy.withOpacity(0.3);
          bgColor = Colors.white;
        } else {
          borderColor = AppColors.sand;
          bgColor = Colors.white;
        }

        return AnimatedContainer(
          duration: const Duration(milliseconds: 150),
          width: 44,
          height: 54,
          decoration: BoxDecoration(
            color: bgColor,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: borderColor, width: 1.5),
          ),
          alignment: Alignment.center,
          child: KeyboardListener(
            focusNode: FocusNode(), // pass-through for key events
            onKeyEvent: onKeyEvent,
            child: TextField(
              controller: controller,
              focusNode: focusNode,
              keyboardType: TextInputType.number,
              textAlign: TextAlign.center,
              maxLength: 6, // allow paste of full code
              style: const TextStyle(
                fontFamily: 'Sora',
                fontSize: 24,
                fontWeight: FontWeight.w800,
                color: AppColors.navy,
                height: 1,
              ),
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
              ],
              decoration: const InputDecoration(
                border: InputBorder.none,
                counterText: '',
                contentPadding: EdgeInsets.zero,
                isDense: true,
              ),
              onChanged: onChanged,
            ),
          ),
        );
      },
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Progress dots (shared with phone_registration_screen)
// ═══════════════════════════════════════════════════════════════════

class _ProgressDots extends StatelessWidget {
  const _ProgressDots({required this.current, required this.total});
  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(total, (i) {
        final isActive = i <= current;
        return Container(
          width: 8,
          height: 8,
          margin: EdgeInsetsDirectional.only(end: i < total - 1 ? 8 : 0),
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isActive
                ? AppColors.gold
                : AppColors.mist.withOpacity(0.3),
          ),
        );
      }),
    );
  }
}
