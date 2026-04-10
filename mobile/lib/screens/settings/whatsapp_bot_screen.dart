import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../core/providers/auth_provider.dart';
import '../../core/providers/core_providers.dart';
import '../../core/theme/animations.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';

// ═══════════════════════════════════════════════════════════════
// Bot Link State
// ═══════════════════════════════════════════════════════════════

class BotLinkState {
  const BotLinkState({
    this.isLinked = false,
    this.isLoading = true,
    this.isEnabling = false,
    this.botPhone,
    this.lastBidText,
    this.lastBidAgo,
  });

  final bool isLinked;
  final bool isLoading;
  final bool isEnabling;
  final String? botPhone;
  final String? lastBidText;
  final String? lastBidAgo;

  BotLinkState copyWith({
    bool? isLinked,
    bool? isLoading,
    bool? isEnabling,
    String? botPhone,
    String? lastBidText,
    String? lastBidAgo,
  }) =>
      BotLinkState(
        isLinked: isLinked ?? this.isLinked,
        isLoading: isLoading ?? this.isLoading,
        isEnabling: isEnabling ?? this.isEnabling,
        botPhone: botPhone ?? this.botPhone,
        lastBidText: lastBidText ?? this.lastBidText,
        lastBidAgo: lastBidAgo ?? this.lastBidAgo,
      );
}

final botLinkProvider =
    StateNotifierProvider.autoDispose<BotLinkNotifier, BotLinkState>((ref) {
  return BotLinkNotifier(ref);
});

class BotLinkNotifier extends StateNotifier<BotLinkState> {
  BotLinkNotifier(this._ref) : super(const BotLinkState()) {
    _fetchStatus();
  }

  final Ref _ref;

  Future<void> _fetchStatus() async {
    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/bot/status');
      final data = resp.data as Map<String, dynamic>;
      state = state.copyWith(
        isLinked: data['is_linked'] as bool? ?? false,
        isLoading: false,
        botPhone: data['bot_phone'] as String?,
        lastBidText: data['last_bid_text'] as String?,
        lastBidAgo: data['last_bid_ago'] as String?,
      );
    } catch (_) {
      state = state.copyWith(isLoading: false);
    }
  }

  Future<void> refresh() => _fetchStatus();

  Future<void> disable() async {
    try {
      final api = _ref.read(apiClientProvider);
      await api.post('/bot/unlink');
      state = state.copyWith(isLinked: false);
    } catch (_) {}
  }
}

// ═══════════════════════════════════════════════════════════════
// Bot Phone Number (for display / QR)
// ═══════════════════════════════════════════════════════════════

const _botPhoneDisplay = '+962 7 9999 0000';
const _botPhoneRaw = '962799990000';
const _waLink = 'https://wa.me/$_botPhoneRaw?text=START';

// ═══════════════════════════════════════════════════════════════
// Screen
// ═══════════════════════════════════════════════════════════════

class WhatsappBotScreen extends ConsumerStatefulWidget {
  const WhatsappBotScreen({super.key});

  @override
  ConsumerState<WhatsappBotScreen> createState() => _WhatsappBotScreenState();
}

class _WhatsappBotScreenState extends ConsumerState<WhatsappBotScreen>
    with TickerProviderStateMixin {
  // Hero step animations
  late AnimationController _step1Controller;
  late AnimationController _step2Controller;
  late AnimationController _step3Controller;

  // Toggle + QR
  bool _botEnabled = false;
  Timer? _pollTimer;

  // Pulsing green dot (linked state)
  late AnimationController _pulseController;

  // Demo chat
  late AnimationController _demoController;
  Timer? _demoLoop;

  @override
  void initState() {
    super.initState();

    // ── Hero step stagger: 200ms apart ──────────────────────────
    _step1Controller = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 400),
    );
    _step2Controller = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 400),
    );
    _step3Controller = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 400),
    );

    // ── Pulse for green dot ─────────────────────────────────────
    _pulseController = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 1400),
    )..repeat(reverse: true);

    // ── Demo chat loop ──────────────────────────────────────────
    _demoController = AnimationController(
      vsync: this, duration: const Duration(milliseconds: 2200),
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _step1Controller.forward();
      Future.delayed(const Duration(milliseconds: 200), () {
        if (mounted) _step2Controller.forward();
      });
      Future.delayed(const Duration(milliseconds: 400), () {
        if (mounted) _step3Controller.forward();
      });
      _startDemoLoop();
    });
  }

  void _startDemoLoop() {
    _demoController.forward();
    _demoLoop = Timer.periodic(const Duration(seconds: 8), (_) {
      if (mounted) {
        _demoController.reset();
        _demoController.forward();
      }
    });
  }

  void _onToggle(bool value) {
    setState(() => _botEnabled = value);
    if (value) {
      HapticFeedback.mediumImpact();
      _startPolling();
    } else {
      _pollTimer?.cancel();
    }
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      await ref.read(botLinkProvider.notifier).refresh();
      final s = ref.read(botLinkProvider);
      if (s.isLinked) {
        _pollTimer?.cancel();
        HapticFeedback.heavyImpact();
      }
    });
  }

  @override
  void dispose() {
    _step1Controller.dispose();
    _step2Controller.dispose();
    _step3Controller.dispose();
    _pulseController.dispose();
    _demoController.dispose();
    _pollTimer?.cancel();
    _demoLoop?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final botState = ref.watch(botLinkProvider);
    final authState = ref.watch(authProvider);
    final userPhone = authState.phone ?? '';

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: true,
        title: const Text(
          'WhatsApp Bidding · المزايدة عبر واتساب',
          style: TextStyle(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: Colors.white,
            fontFamily: 'Sora',
          ),
        ),
      ),
      body: botState.isLoading
          ? const Center(
              child: CircularProgressIndicator(color: AppColors.navy),
            )
          : ListView(
              padding: const EdgeInsetsDirectional.all(AppSpacing.md),
              children: [
                // ── Hero Explainer ──────────────────────────────
                _HeroExplainer(
                  step1: _step1Controller,
                  step2: _step2Controller,
                  step3: _step3Controller,
                ),
                const SizedBox(height: AppSpacing.md),

                // ── How It Works ────────────────────────────────
                const _HowItWorks(),
                const SizedBox(height: AppSpacing.md),

                // ── Link / Status Section ───────────────────────
                if (botState.isLinked)
                  _LinkedState(
                    botState: botState,
                    pulseController: _pulseController,
                    onDisable: () => _showDisableDialog(context),
                  )
                else
                  _UnlinkedState(
                    userPhone: userPhone,
                    botEnabled: _botEnabled,
                    onToggle: _onToggle,
                    isLinked: botState.isLinked,
                  ),
                const SizedBox(height: AppSpacing.md),

                // ── Demo Section ────────────────────────────────
                _DemoSection(animation: _demoController),
                const SizedBox(height: AppSpacing.xxl),
              ],
            ),
    );
  }

  Future<void> _showDisableDialog(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Disable WhatsApp Bot?'),
        content: const Text(
          'You won\'t be able to bid via WhatsApp until you re-enable it.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            style: TextButton.styleFrom(foregroundColor: AppColors.ember),
            child: const Text('Disable'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) {
      await ref.read(botLinkProvider.notifier).disable();
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// Hero Explainer — 3-step illustration
// ═══════════════════════════════════════════════════════════════

class _HeroExplainer extends StatelessWidget {
  const _HeroExplainer({
    required this.step1,
    required this.step2,
    required this.step3,
  });

  final AnimationController step1;
  final AnimationController step2;
  final AnimationController step3;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        _AnimatedStepCircle(
          animation: step1,
          icon: Icons.phone_android_rounded,
        ),
        _GoldArrow(animation: step1),
        _AnimatedStepCircle(
          animation: step2,
          icon: Icons.chat_rounded,
        ),
        _GoldArrow(animation: step2),
        _AnimatedStepCircle(
          animation: step3,
          icon: Icons.gavel_rounded,
        ),
      ],
    );
  }
}

class _AnimatedStepCircle extends StatelessWidget {
  const _AnimatedStepCircle({
    required this.animation,
    required this.icon,
  });

  final AnimationController animation;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: animation,
      builder: (_, child) {
        final scale = Curves.elasticOut.transform(animation.value);
        return Transform.scale(scale: scale, child: child);
      },
      child: Container(
        width: 56,
        height: 56,
        decoration: const BoxDecoration(
          color: AppColors.navy,
          shape: BoxShape.circle,
        ),
        child: Icon(icon, color: Colors.white, size: 26),
      ),
    );
  }
}

class _GoldArrow extends StatelessWidget {
  const _GoldArrow({required this.animation});
  final AnimationController animation;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: animation,
      builder: (_, child) {
        return Opacity(
          opacity: animation.value.clamp(0.0, 1.0),
          child: child,
        );
      },
      child: const Padding(
        padding: EdgeInsetsDirectional.symmetric(horizontal: AppSpacing.xs),
        child: Icon(
          Icons.arrow_forward_rounded,
          color: AppColors.gold,
          size: 22,
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// How It Works
// ═══════════════════════════════════════════════════════════════

class _HowItWorks extends StatelessWidget {
  const _HowItWorks();

  static const _steps = [
    (
      en: 'Link your WhatsApp number below',
      ar: 'اربط رقم واتساب أدناه',
    ),
    (
      en: 'Send a voice note or text to our bot: "Bid 650 on iPhone"',
      ar: 'أرسل رسالة صوتية أو نصية للبوت: "ازيد ٦٥٠ على الايفون"',
    ),
    (
      en: 'We bid instantly on your behalf. You get a confirmation.',
      ar: 'نزايد فوراً نيابة عنك. ستصلك رسالة تأكيد.',
    ),
    (
      en: 'Supports 5 Arabic dialects: Jordanian, Saudi, Gulf, Egyptian, Levantine',
      ar: 'يدعم ٥ لهجات عربية: أردنية، سعودية، خليجية، مصرية، شامية',
    ),
  ];

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.cream,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'How it works · كيف يعمل',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w700,
              color: AppColors.navy,
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          ...List.generate(_steps.length, (i) {
            final step = _steps[i];
            return Padding(
              padding: const EdgeInsetsDirectional.only(bottom: AppSpacing.sm),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Number badge
                  Container(
                    width: 22,
                    height: 22,
                    decoration: const BoxDecoration(
                      color: AppColors.navy,
                      shape: BoxShape.circle,
                    ),
                    child: Center(
                      child: Text(
                        '${i + 1}',
                        style: const TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.w700,
                          color: Colors.white,
                          fontFamily: 'Sora',
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          step.en,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: AppColors.ink,
                            height: 1.3,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          step.ar,
                          style: const TextStyle(
                            fontSize: 12,
                            fontWeight: FontWeight.w500,
                            color: AppColors.mist,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Linked State
// ═══════════════════════════════════════════════════════════════

class _LinkedState extends StatelessWidget {
  const _LinkedState({
    required this.botState,
    required this.pulseController,
    required this.onDisable,
  });

  final BotLinkState botState;
  final AnimationController pulseController;
  final VoidCallback onDisable;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Green banner
        Container(
          padding: const EdgeInsetsDirectional.all(AppSpacing.md),
          decoration: BoxDecoration(
            color: AppColors.emerald.withOpacity(0.08),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: AppColors.emerald.withOpacity(0.25),
              width: 1,
            ),
          ),
          child: Row(
            children: [
              // Pulsing green dot
              AnimatedBuilder(
                animation: pulseController,
                builder: (_, child) {
                  final opacity =
                      0.4 + 0.6 * Curves.easeInOut.transform(pulseController.value);
                  return Opacity(opacity: opacity, child: child);
                },
                child: Container(
                  width: 10,
                  height: 10,
                  decoration: const BoxDecoration(
                    color: AppColors.emerald,
                    shape: BoxShape.circle,
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Bot active · البوت نشط',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w700,
                        color: AppColors.emerald,
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      'WhatsApp bidding is enabled for your account',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: AppColors.mist,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.check_circle_rounded,
                color: AppColors.emerald,
                size: 28,
              ),
            ],
          ),
        ),

        // Last bid info
        if (botState.lastBidText != null) ...[
          const SizedBox(height: AppSpacing.sm),
          Container(
            padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.sand, width: 1),
            ),
            child: Row(
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: AppColors.navy.withOpacity(0.08),
                    borderRadius: AppSpacing.radiusSm,
                  ),
                  child: const Icon(
                    Icons.gavel_rounded,
                    color: AppColors.navy,
                    size: 18,
                  ),
                ),
                const SizedBox(width: AppSpacing.xs),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Your last bot bid',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w600,
                          color: AppColors.mist,
                          letterSpacing: 0.3,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        botState.lastBidText!,
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: AppColors.ink,
                        ),
                      ),
                    ],
                  ),
                ),
                if (botState.lastBidAgo != null)
                  Text(
                    botState.lastBidAgo!,
                    style: const TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w500,
                      color: AppColors.mist,
                    ),
                  ),
              ],
            ),
          ),
        ],

        // Disable link
        const SizedBox(height: AppSpacing.md),
        GestureDetector(
          onTap: onDisable,
          child: const Text(
            'Disable bot · إلغاء تفعيل البوت',
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: AppColors.ember,
              decoration: TextDecoration.underline,
              decorationColor: AppColors.ember,
            ),
          ),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Unlinked State — toggle, QR, instructions
// ═══════════════════════════════════════════════════════════════

class _UnlinkedState extends StatelessWidget {
  const _UnlinkedState({
    required this.userPhone,
    required this.botEnabled,
    required this.onToggle,
    required this.isLinked,
  });

  final String userPhone;
  final bool botEnabled;
  final ValueChanged<bool> onToggle;
  final bool isLinked;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Phone display
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: AppColors.navy.withOpacity(0.08),
                  borderRadius: AppSpacing.radiusSm,
                ),
                child: const Icon(
                  Icons.phone_android_rounded,
                  color: AppColors.navy,
                  size: 20,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      userPhone.isNotEmpty ? userPhone : 'No phone number',
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: AppColors.ink,
                        fontFamily: 'Sora',
                        letterSpacing: 0.5,
                      ),
                      textDirection: TextDirection.ltr,
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'This number will receive bot messages',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: AppColors.mist,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),

          // Toggle
          Container(
            padding: const EdgeInsetsDirectional.symmetric(
              horizontal: AppSpacing.sm,
              vertical: AppSpacing.xs,
            ),
            decoration: BoxDecoration(
              color: AppColors.cream,
              borderRadius: AppSpacing.radiusMd,
            ),
            child: Row(
              children: [
                const Icon(Icons.chat_rounded, color: AppColors.navy, size: 20),
                const SizedBox(width: AppSpacing.xs),
                const Expanded(
                  child: Text(
                    'Enable WhatsApp bidding',
                    style: TextStyle(
                      fontSize: 14,
                      fontWeight: FontWeight.w600,
                      color: AppColors.ink,
                    ),
                  ),
                ),
                Switch.adaptive(
                  value: botEnabled,
                  onChanged: onToggle,
                  activeColor: AppColors.emerald,
                ),
              ],
            ),
          ),

          // QR + instructions (animated reveal)
          AnimatedSize(
            duration: AppAnimations.enter,
            curve: AppAnimations.enterCurve,
            child: botEnabled && !isLinked
                ? _QrSection()
                : const SizedBox.shrink(),
          ),

          // Success state (after polling detects link)
          if (isLinked) ...[
            const SizedBox(height: AppSpacing.md),
            _SuccessCheckmark(),
          ],
        ],
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// QR Code + Instructions
// ═══════════════════════════════════════════════════════════════

class _QrSection extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const SizedBox(height: AppSpacing.md),
        const Divider(color: AppColors.sand, height: 1),
        const SizedBox(height: AppSpacing.md),

        // QR Code
        Container(
          padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: AppColors.sand, width: 1),
          ),
          child: QrImageView(
            data: _waLink,
            version: QrVersions.auto,
            size: 180,
            eyeStyle: const QrEyeStyle(
              eyeShape: QrEyeShape.circle,
              color: AppColors.navy,
            ),
            dataModuleStyle: const QrDataModuleStyle(
              dataModuleShape: QrDataModuleShape.circle,
              color: AppColors.navy,
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.sm),

        // Instructions
        const Text(
          'Scan or tap to open WhatsApp, then send "START"',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: AppColors.ink,
          ),
        ),
        const SizedBox(height: 4),
        const Text(
          'امسح الرمز أو اضغط لفتح واتساب، ثم أرسل "START"',
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w500,
            color: AppColors.mist,
          ),
        ),
        const SizedBox(height: AppSpacing.md),

        // OR divider
        Row(
          children: [
            const Expanded(child: Divider(color: AppColors.sand)),
            Padding(
              padding: const EdgeInsetsDirectional.symmetric(
                horizontal: AppSpacing.sm,
              ),
              child: Text(
                'OR',
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.w700,
                  color: AppColors.mist.withOpacity(0.7),
                  letterSpacing: 1,
                ),
              ),
            ),
            const Expanded(child: Divider(color: AppColors.sand)),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),

        // Copy phone row
        Container(
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: AppColors.cream,
            borderRadius: AppSpacing.radiusMd,
          ),
          child: Row(
            children: [
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Send "START" to',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w500,
                        color: AppColors.mist,
                      ),
                    ),
                    SizedBox(height: 2),
                    Text(
                      _botPhoneDisplay,
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        color: AppColors.navy,
                        fontFamily: 'Sora',
                        letterSpacing: 0.5,
                      ),
                      textDirection: TextDirection.ltr,
                    ),
                  ],
                ),
              ),
              _CopyButton(text: _botPhoneRaw),
            ],
          ),
        ),

        // Polling indicator
        const SizedBox(height: AppSpacing.md),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                strokeWidth: 1.5,
                color: AppColors.mist.withOpacity(0.5),
              ),
            ),
            const SizedBox(width: AppSpacing.xs),
            const Text(
              'Waiting for "START" message...',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: AppColors.mist,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _CopyButton extends StatefulWidget {
  const _CopyButton({required this.text});
  final String text;

  @override
  State<_CopyButton> createState() => _CopyButtonState();
}

class _CopyButtonState extends State<_CopyButton> {
  bool _copied = false;

  void _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.text));
    HapticFeedback.lightImpact();
    setState(() => _copied = true);
    Future.delayed(const Duration(seconds: 2), () {
      if (mounted) setState(() => _copied = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: _copy,
      child: Container(
        padding: const EdgeInsetsDirectional.symmetric(
          horizontal: AppSpacing.sm,
          vertical: AppSpacing.xs,
        ),
        decoration: BoxDecoration(
          color: _copied ? AppColors.emerald : AppColors.navy,
          borderRadius: AppSpacing.radiusSm,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              _copied ? Icons.check_rounded : Icons.copy_rounded,
              color: Colors.white,
              size: 14,
            ),
            const SizedBox(width: 4),
            Text(
              _copied ? 'Copied' : 'Copy',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w700,
                color: Colors.white,
                fontFamily: 'Sora',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Success Checkmark
// ═══════════════════════════════════════════════════════════════

class _SuccessCheckmark extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 500),
      curve: Curves.elasticOut,
      builder: (_, value, child) {
        return Transform.scale(scale: value, child: child);
      },
      child: Container(
        padding: const EdgeInsetsDirectional.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: AppColors.emerald.withOpacity(0.08),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: AppColors.emerald.withOpacity(0.25),
            width: 1,
          ),
        ),
        child: const Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              Icons.check_circle_rounded,
              color: AppColors.emerald,
              size: 24,
            ),
            SizedBox(width: AppSpacing.xs),
            Text(
              'WhatsApp bot active \u2713',
              style: TextStyle(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: AppColors.emerald,
                fontFamily: 'Sora',
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════
// Demo Section — animated chat bubbles
// ═══════════════════════════════════════════════════════════════

class _DemoSection extends StatelessWidget {
  const _DemoSection({required this.animation});
  final AnimationController animation;

  @override
  Widget build(BuildContext context) {
    // User bubble: 0.0–0.27 (300ms of 2200ms total ~= 0.136, but we use interval)
    // Bot bubble: starts at 800ms = 0.364 of 2200ms
    final userBubble = CurvedAnimation(
      parent: animation,
      curve: const Interval(0.0, 0.27, curve: Curves.easeOut),
    );
    final botBubble = CurvedAnimation(
      parent: animation,
      curve: const Interval(0.36, 0.63, curve: Curves.easeOut),
    );

    return Container(
      padding: const EdgeInsetsDirectional.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: AppColors.cream,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.sand, width: 1),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.play_circle_rounded, color: AppColors.navy, size: 18),
              SizedBox(width: AppSpacing.xs),
              Text(
                'Try a sample command · جرّب أمراً',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                  color: AppColors.navy,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),

          // Chat area
          Container(
            padding: const EdgeInsetsDirectional.all(AppSpacing.sm),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(12),
            ),
            child: Column(
              children: [
                // User bubble (right-aligned)
                _ChatBubble(
                  animation: userBubble,
                  text: 'bid 650 on iphone',
                  isUser: true,
                ),
                const SizedBox(height: AppSpacing.sm),
                // Bot response (left-aligned)
                _ChatBubble(
                  animation: botBubble,
                  text:
                      '\u2705 Bid placed: 650 JOD on iPhone 14 Pro. You\'re leading!',
                  isUser: false,
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ChatBubble extends StatelessWidget {
  const _ChatBubble({
    required this.animation,
    required this.text,
    required this.isUser,
  });

  final Animation<double> animation;
  final String text;
  final bool isUser;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: animation,
      builder: (_, child) {
        // slideRight + fadeIn
        final dx = (1 - animation.value) * (isUser ? 30 : -30);
        return Opacity(
          opacity: animation.value.clamp(0.0, 1.0),
          child: Transform.translate(
            offset: Offset(dx, 0),
            child: child,
          ),
        );
      },
      child: Align(
        alignment:
            isUser ? AlignmentDirectional.centerEnd : AlignmentDirectional.centerStart,
        child: Container(
          constraints: BoxConstraints(
            maxWidth: MediaQuery.of(context).size.width * 0.65,
          ),
          padding: const EdgeInsetsDirectional.symmetric(
            horizontal: AppSpacing.sm,
            vertical: AppSpacing.xs,
          ),
          decoration: BoxDecoration(
            color: isUser
                ? const Color(0xFFDCF8C6) // WhatsApp green bubble
                : AppColors.sand,
            borderRadius: BorderRadius.only(
              topLeft: const Radius.circular(12),
              topRight: const Radius.circular(12),
              bottomLeft: Radius.circular(isUser ? 12 : 2),
              bottomRight: Radius.circular(isUser ? 2 : 12),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!isUser)
                const Padding(
                  padding: EdgeInsetsDirectional.only(bottom: 2),
                  child: Text(
                    'MZADAK Bot',
                    style: TextStyle(
                      fontSize: 9,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                      letterSpacing: 0.3,
                    ),
                  ),
                ),
              Text(
                text,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: isUser ? AppColors.ink : AppColors.ink,
                  height: 1.3,
                ),
              ),
              const SizedBox(height: 2),
              Align(
                alignment: AlignmentDirectional.centerEnd,
                child: Text(
                  isUser ? '10:32 PM' : '10:32 PM',
                  style: TextStyle(
                    fontSize: 9,
                    fontWeight: FontWeight.w500,
                    color: AppColors.mist.withOpacity(0.7),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
