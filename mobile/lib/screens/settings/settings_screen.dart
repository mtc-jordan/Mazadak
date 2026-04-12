import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:local_auth/local_auth.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/l10n/locale_provider.dart';
import '../../core/providers/auth_provider.dart';
import '../../core/router.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';
import '../../l10n/app_localizations.dart';

// ══════════════════════════════════════════════════════════════════
// Settings Screen
// ══════════════════════════════════════════════════════════════════

class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  bool _biometricEnabled = false;
  bool _biometricAvailable = false;
  int _selectedLang = 0; // 0 = English, 1 = Arabic
  int _selectedTheme = 0; // 0 = Light, 1 = Dark, 2 = System
  int _versionTapCount = 0;
  String _appVersion = '';
  final _localAuth = LocalAuthentication();

  @override
  void initState() {
    super.initState();
    _loadPrefs();
    _checkBiometrics();
    _loadVersion();
  }

  Future<void> _loadVersion() async {
    final info = await PackageInfo.fromPlatform();
    if (mounted) {
      setState(() => _appVersion = '${info.version} (build ${info.buildNumber})');
    }
  }

  Future<void> _checkBiometrics() async {
    try {
      final canCheck = await _localAuth.canCheckBiometrics;
      final isSupported = await _localAuth.isDeviceSupported();
      if (mounted) {
        setState(() => _biometricAvailable = canCheck && isSupported);
      }
    } catch (_) {
      // Biometrics not available
    }
  }

  Future<void> _loadPrefs() async {
    final locale = ref.read(localeProvider);
    setState(() {
      _selectedLang = locale.languageCode == 'ar' ? 1 : 0;
    });
  }

  Future<void> _setLang(int index) async {
    setState(() => _selectedLang = index);
    final locale = index == 1
        ? const Locale('ar', 'JO')
        : const Locale('en', 'US');
    ref.read(localeProvider.notifier).setLocale(locale);
  }

  Future<void> _setBiometric(bool value) async {
    if (value) {
      // Verify identity before enabling
      try {
        final authenticated = await _localAuth.authenticate(
          localizedReason: 'Verify your identity',
        );
        if (!authenticated) return;
      } catch (_) {
        return;
      }
    }
    setState(() => _biometricEnabled = value);
  }

  void _setTheme(int index) {
    if (index != 0) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(S.of(context).settingsDarkModeSoon),
          duration: const Duration(seconds: 2),
        ),
      );
      return;
    }
    setState(() => _selectedTheme = index);
  }

  Future<void> _logout() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(S.of(context).settingsLogoutTitle),
        content: const Text(
          'You will need to sign in again with your phone number.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(S.of(context).cancel),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(context, true),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.ember,
              foregroundColor: Colors.white,
            ),
            child: Text(S.of(context).settingsLogout),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    await ref.read(authProvider.notifier).logout();
    if (mounted) {
      context.go(AppRoutes.welcome);
    }
  }

  void _deleteAccount() {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text(
          'Delete your account?',
          style: TextStyle(color: AppColors.ember),
        ),
        content: const Text(
          'This will permanently delete your account, all listings, '
          'bid history, and transaction records. This action cannot be undone.\n\n'
          'Any active escrow transactions must be completed first.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(S.of(context).cancel),
          ),
          ElevatedButton(
            onPressed: () {
              Navigator.pop(context);
              _showDeleteConfirmation();
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.ember,
              foregroundColor: Colors.white,
            ),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
  }

  void _showDeleteConfirmation() {
    final controller = TextEditingController();
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(S.of(context).settingsDeleteConfirmTitle),
        content: TextField(
          controller: controller,
          decoration: InputDecoration(
            hintText: S.of(context).settingsDeleteConfirmHint,
            border: OutlineInputBorder(),
          ),
          textCapitalization: TextCapitalization.characters,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: Text(S.of(context).cancel),
          ),
          ElevatedButton(
            onPressed: () {
              if (controller.text.trim().toUpperCase() == 'DELETE') {
                Navigator.pop(context);
                // Would call API DELETE /auth/me then logout
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(S.of(context).settingsAccountDeleted),
                    backgroundColor: AppColors.ember,
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppColors.ember,
              foregroundColor: Colors.white,
            ),
            child: Text(S.of(context).delete),
          ),
        ],
      ),
    );
  }

  Future<void> _launchUrl(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
  }

  void _reportBug() {
    final auth = ref.read(authProvider);
    final body = Uri.encodeComponent(
      '\n\n---\n'
      'App: MZADAK v1.0.0 (1)\n'
      'Platform: ${Theme.of(context).platform.name}\n'
      'User: ${auth.userId ?? 'unknown'}\n',
    );
    _launchUrl('mailto:support@mzadak.com?subject=Bug%20Report&body=$body');
  }

  void _onVersionTap() {
    if (!kDebugMode) return;
    _versionTapCount++;
    if (_versionTapCount >= 3) {
      _versionTapCount = 0;
      _showDebugInfo();
    }
  }

  void _showDebugInfo() {
    final auth = ref.read(authProvider);
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(S.of(context).settingsDebugInfo),
        content: Text(
          'User ID: ${auth.userId ?? 'N/A'}\n'
          'Phone: ${auth.phone ?? 'N/A'}\n'
          'Role: ${auth.role ?? 'N/A'}\n'
          'KYC: ${auth.kycStatus ?? 'N/A'}\n'
          'Auth: ${auth.status.name}\n'
          'Build: 1.0.0 (1)',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        title: const Column(
          children: [
            Text(
              'Settings',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'الإعدادات',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        centerTitle: true,
      ),
      body: ListView(
        padding: const EdgeInsets.only(
          top: AppSpacing.sm,
          bottom: AppSpacing.xxxl,
        ),
        children: [
          // ── Profile summary card ───────────────────────────────
          _ProfileCard(auth: auth),

          const SizedBox(height: AppSpacing.sm),

          // ── Account ────────────────────────────────────────────
          _SectionLabel('ACCOUNT'),
          _SettingsCard(children: [
            _SettingsTile(
              icon: Icons.person_rounded,
              label: S.of(context).settingsEditProfile,
              onTap: () {}, // → EditProfileScreen
            ),
            _SettingsTile(
              icon: Icons.phone_rounded,
              label: S.of(context).settingsPhone,
              trailing: Text(
                _maskPhone(auth.phone),
                style: const TextStyle(fontSize: 12, color: AppColors.mist),
              ),
              onTap: () {},
            ),
            _SettingsTile(
              icon: Icons.email_rounded,
              label: S.of(context).settingsEmail,
              trailing: const Text(
                'Add',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.gold,
                ),
              ),
              onTap: () {},
            ),
            _LanguageTile(
              selectedIndex: _selectedLang,
              onChanged: _setLang,
            ),
            _SettingsTile(
              icon: Icons.notifications_rounded,
              label: S.of(context).settingsNotifications,
              onTap: () {}, // → NotificationPreferencesScreen
            ),
          ]),

          const SizedBox(height: AppSpacing.sm),

          // ── Seller ─────────────────────────────────────────────
          _SectionLabel('SELLER'),
          _SettingsCard(children: [
            _SettingsTile(
              icon: Icons.storefront_rounded,
              label: S.of(context).settingsMyListings,
              onTap: () => context.push(AppRoutes.myListings),
            ),
            _SettingsTile(
              icon: Icons.account_balance_rounded,
              label: S.of(context).settingsPayoutBank,
              onTap: () {}, // → BankAccountScreen
            ),
            _SettingsTile(
              icon: Icons.analytics_rounded,
              label: S.of(context).settingsSellerAnalytics,
              onTap: () {}, // → AnalyticsScreen
            ),
            _ProSellerTile(isSubscribed: auth.role == 'pro_seller'),
          ]),

          const SizedBox(height: AppSpacing.sm),

          // ── Appearance ─────────────────────────────────────────
          _SectionLabel('APPEARANCE'),
          _SettingsCard(children: [
            _ThemeTile(
              selectedIndex: _selectedTheme,
              onChanged: _setTheme,
            ),
          ]),

          const SizedBox(height: AppSpacing.sm),

          // ── Security ───────────────────────────────────────────
          _SectionLabel('SECURITY'),
          _SettingsCard(children: [
            if (_biometricAvailable)
              _SettingsTile(
                icon: Icons.fingerprint_rounded,
                label: S.of(context).settingsBiometric,
                trailing: Switch.adaptive(
                  value: _biometricEnabled,
                  onChanged: _setBiometric,
                  activeColor: AppColors.navy,
                ),
                onTap: () => _setBiometric(!_biometricEnabled),
              ),
            _SettingsTile(
              icon: Icons.devices_rounded,
              label: S.of(context).settingsActiveSessions,
              onTap: () {}, // → ActiveSessionsScreen
            ),
            _SettingsTile(
              icon: Icons.delete_forever_rounded,
              label: S.of(context).settingsDeleteAccount,
              labelColor: AppColors.ember,
              onTap: _deleteAccount,
              showChevron: false,
            ),
          ]),

          const SizedBox(height: AppSpacing.sm),

          // ── Support ────────────────────────────────────────────
          _SectionLabel('SUPPORT'),
          _SettingsCard(children: [
            _SettingsTile(
              icon: Icons.help_outline_rounded,
              label: S.of(context).settingsHelpCenter,
              onTap: () => _launchUrl('https://mzadak.com/help'),
            ),
            _SettingsTile(
              icon: Icons.bug_report_rounded,
              label: S.of(context).settingsReportBug,
              onTap: _reportBug,
            ),
            _SettingsTile(
              icon: Icons.privacy_tip_rounded,
              label: S.of(context).settingsPrivacyPolicy,
              onTap: () => _launchUrl('https://mzadak.com/privacy'),
            ),
            _SettingsTile(
              icon: Icons.description_rounded,
              label: S.of(context).settingsTerms,
              onTap: () => _launchUrl('https://mzadak.com/terms'),
            ),
          ]),

          const SizedBox(height: AppSpacing.sm),

          // ── Version ────────────────────────────────────────────
          GestureDetector(
            onTap: _onVersionTap,
            behavior: HitTestBehavior.opaque,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Center(
                child: Text(
                  _appVersion.isNotEmpty ? _appVersion : '...',
                  style: const TextStyle(
                    fontSize: 12,
                    color: AppColors.mist,
                  ),
                ),
              ),
            ),
          ),

          const SizedBox(height: AppSpacing.xs),

          // ── Log out ────────────────────────────────────────────
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
            child: GestureDetector(
              onTap: _logout,
              child: Container(
                width: double.infinity,
                height: 48,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppColors.ember, width: 1.5),
                ),
                child: Center(
                  child: Text(
                    S.of(context).settingsLogout,
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.ember,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _maskPhone(String? phone) {
    if (phone == null || phone.length < 6) return 'Not set';
    // +962 7XX XXX XXX
    final prefix = phone.substring(0, 5);
    return '$prefix** *** ***';
  }
}

// ══════════════════════════════════════════════════════════════════
// Profile Summary Card
// ══════════════════════════════════════════════════════════════════

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.auth});
  final AuthState auth;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push('/profile/ats'),
      child: Container(
        margin: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
        padding: AppSpacing.allMd,
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(14),
        ),
        child: Row(
          children: [
            // Avatar
            Container(
              width: 52,
              height: 52,
              decoration: BoxDecoration(
                color: AppColors.navy.withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: Center(
                child: Text(
                  _initial(auth.fullNameAr),
                  style: const TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                    color: AppColors.navy,
                  ),
                ),
              ),
            ),
            const SizedBox(width: AppSpacing.sm),

            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    auth.fullNameAr ?? 'User',
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: AppColors.navy,
                    ),
                  ),
                  if (auth.phone != null)
                    Text(
                      auth.phone!,
                      style: const TextStyle(
                        fontSize: 12,
                        color: AppColors.mist,
                      ),
                    ),
                ],
              ),
            ),

            // ATS score pill
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.gold.withOpacity(0.12),
                borderRadius: BorderRadius.circular(14),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.shield_rounded,
                      size: 14, color: AppColors.gold),
                  const SizedBox(width: 4),
                  const Text(
                    'ATS',
                    style: TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 11,
                      fontWeight: FontWeight.w700,
                      color: AppColors.gold,
                    ),
                  ),
                ],
              ),
            ),

            const SizedBox(width: AppSpacing.xs),
            const Icon(Icons.chevron_right_rounded,
                color: AppColors.mist, size: 20),
          ],
        ),
      ),
    );
  }

  String _initial(String? name) {
    if (name == null || name.isEmpty) return 'م';
    return name.characters.first;
  }
}

// ══════════════════════════════════════════════════════════════════
// Section label
// ══════════════════════════════════════════════════════════════════

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.label);
  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(
        start: AppSpacing.md + 4,
        top: AppSpacing.sm,
        bottom: AppSpacing.xxs,
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontFamily: 'Sora',
          fontSize: 11,
          fontWeight: FontWeight.w700,
          color: AppColors.mist,
          letterSpacing: 1,
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Settings card — white card wrapping a group of tiles
// ══════════════════════════════════════════════════════════════════

class _SettingsCard extends StatelessWidget {
  const _SettingsCard({required this.children});
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: AppSpacing.md),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(14),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: [
          for (int i = 0; i < children.length; i++) ...[
            children[i],
            if (i < children.length - 1)
              const Divider(
                height: 0.5,
                indent: 52,
                color: AppColors.sand,
              ),
          ],
        ],
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Settings tile — standard row with icon, label, trailing, chevron
// ══════════════════════════════════════════════════════════════════

class _SettingsTile extends StatelessWidget {
  const _SettingsTile({
    required this.icon,
    required this.label,
    required this.onTap,
    this.trailing,
    this.labelColor,
    this.showChevron = true,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final Widget? trailing;
  final Color? labelColor;
  final bool showChevron;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        child: Row(
          children: [
            Icon(icon, size: 20, color: labelColor ?? AppColors.navy),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                label,
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                  color: labelColor ?? AppColors.ink,
                ),
              ),
            ),
            if (trailing != null) trailing!,
            if (showChevron && trailing is! Switch)
              const Padding(
                padding: EdgeInsetsDirectional.only(start: 4),
                child: Icon(Icons.chevron_right_rounded,
                    color: AppColors.mist, size: 20),
              ),
          ],
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Language tile — inline toggle
// ══════════════════════════════════════════════════════════════════

class _LanguageTile extends StatelessWidget {
  const _LanguageTile({
    required this.selectedIndex,
    required this.onChanged,
  });

  final int selectedIndex;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xs,
      ),
      child: Row(
        children: [
          const Icon(Icons.language_rounded, size: 20, color: AppColors.navy),
          const SizedBox(width: AppSpacing.sm),
          const Expanded(
            child: Text(
              'Language',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w500,
                color: AppColors.ink,
              ),
            ),
          ),
          _InlineToggle(
            labels: const ['EN', 'AR'],
            selectedIndex: selectedIndex,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Theme tile — 3-way toggle
// ══════════════════════════════════════════════════════════════════

class _ThemeTile extends StatelessWidget {
  const _ThemeTile({
    required this.selectedIndex,
    required this.onChanged,
  });

  final int selectedIndex;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xs,
      ),
      child: Row(
        children: [
          const Icon(Icons.palette_rounded, size: 20, color: AppColors.navy),
          const SizedBox(width: AppSpacing.sm),
          const Expanded(
            child: Text(
              'Theme',
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w500,
                color: AppColors.ink,
              ),
            ),
          ),
          _InlineToggle(
            labels: const ['Light', 'Dark', 'System'],
            selectedIndex: selectedIndex,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Pro Seller tile
// ══════════════════════════════════════════════════════════════════

class _ProSellerTile extends StatelessWidget {
  const _ProSellerTile({required this.isSubscribed});
  final bool isSubscribed;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () {},
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.sm,
        ),
        child: Row(
          children: [
            const Icon(Icons.workspace_premium_rounded,
                size: 20, color: AppColors.gold),
            const SizedBox(width: AppSpacing.sm),
            const Expanded(
              child: Text(
                'Pro seller plan',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w500,
                  color: AppColors.ink,
                ),
              ),
            ),
            if (isSubscribed)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: AppColors.gold,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: const Text(
                  'PRO',
                  style: TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 10,
                    fontWeight: FontWeight.w800,
                    color: Colors.white,
                  ),
                ),
              )
            else
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.gold.withOpacity(0.12),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Text(
                  'Upgrade',
                  style: TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: AppColors.gold,
                  ),
                ),
              ),
            const SizedBox(width: 4),
            const Icon(Icons.chevron_right_rounded,
                color: AppColors.mist, size: 20),
          ],
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Inline Toggle — compact pill-style toggle for 2-3 options
// ══════════════════════════════════════════════════════════════════

class _InlineToggle extends StatelessWidget {
  const _InlineToggle({
    required this.labels,
    required this.selectedIndex,
    required this.onChanged,
  });

  final List<String> labels;
  final int selectedIndex;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 32,
      decoration: BoxDecoration(
        color: AppColors.sand.withOpacity(0.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(labels.length, (i) {
          final isActive = i == selectedIndex;
          return GestureDetector(
            onTap: () => onChanged(i),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              curve: Curves.easeOutCubic,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: isActive ? AppColors.navy : Colors.transparent,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                labels[i],
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: isActive ? Colors.white : AppColors.mist,
                ),
              ),
            ),
          );
        }),
      ),
    );
  }
}
