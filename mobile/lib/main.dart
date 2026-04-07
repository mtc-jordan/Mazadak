import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/l10n/locale_provider.dart';
import 'core/router.dart';
import 'core/theme/theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Lock to portrait orientation
  await SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);

  // Initialize Arabic date formatting data
  await initializeDateFormatting('ar_JO', null);

  runApp(const ProviderScope(child: MzadakApp()));
}

class MzadakApp extends ConsumerWidget {
  const MzadakApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    final locale = ref.watch(localeProvider);

    return MaterialApp.router(
      title: 'MZADAK',

      // ── Theme ─────────────────────────────────────────────────
      theme: MzadakTheme.light(),
      darkTheme: MzadakTheme.dark(),
      themeMode: ThemeMode.system,

      // ── Localization ──────────────────────────────────────────
      locale: locale,
      supportedLocales: supportedLocales,
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],

      // ── Router ────────────────────────────────────────────────
      routerConfig: router,

      debugShowCheckedModeBanner: false,

      // ── RTL-aware builder ─────────────────────────────────────
      builder: (context, child) {
        return Directionality(
          textDirection:
              locale.languageCode == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          child: child ?? const SizedBox.shrink(),
        );
      },
    );
  }
}
