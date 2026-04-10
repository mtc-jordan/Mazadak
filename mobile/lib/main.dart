import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/date_symbol_data_local.dart';

import 'core/l10n/locale_provider.dart';
import 'core/router.dart';
import 'core/theme/theme.dart';
import 'package:go_router/go_router.dart';

/// Global navigator key for routing from FCM handlers.
final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();

/// Global scaffold messenger key for showing snackbars from FCM handlers.
final GlobalKey<ScaffoldMessengerState> scaffoldMessengerKey =
    GlobalKey<ScaffoldMessengerState>();

/// Handle FCM messages when app is in background/terminated.
@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
}

/// Route to the correct screen based on FCM notification data.
void _handleNotificationNavigation(RemoteMessage message) {
  final data = message.data;
  final type = data['type'] as String? ?? '';
  final id = data['resource_id'] as String?;
  if (id == null) return;

  final context = navigatorKey.currentContext;
  if (context == null) return;

  if (type == 'outbid') {
    HapticFeedback.heavyImpact();
  }

  if (type.startsWith('bid') || type.contains('auction')) {
    GoRouter.of(context).push('/auction/$id');
  } else if (type.startsWith('escrow')) {
    GoRouter.of(context).push('/escrow/$id');
  } else if (type.contains('listing')) {
    GoRouter.of(context).push('/listing/$id');
  }
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize Firebase (gracefully skip if google-services.json missing)
  try {
    await Firebase.initializeApp();
    FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

    // Handle foreground messages — show in-app banner
    FirebaseMessaging.onMessage.listen((RemoteMessage message) {
      final notification = message.notification;
      if (notification == null) return;
      final messenger = scaffoldMessengerKey.currentState;
      if (messenger == null) return;
      messenger.showSnackBar(SnackBar(
        content: Text(notification.body ?? notification.title ?? ''),
        action: SnackBarAction(
          label: 'عرض',
          onPressed: () => _handleNotificationNavigation(message),
        ),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 4),
      ));
    });

    // Handle notification taps when app is in background
    FirebaseMessaging.onMessageOpenedApp.listen(_handleNotificationNavigation);

    // Handle notification tap that launched the app from terminated state
    final initialMessage = await FirebaseMessaging.instance.getInitialMessage();
    if (initialMessage != null) {
      // Defer navigation until after app is built
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _handleNotificationNavigation(initialMessage);
      });
    }
  } catch (e) {
    debugPrint('Firebase init skipped: $e');
  }

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
      scaffoldMessengerKey: scaffoldMessengerKey,
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
