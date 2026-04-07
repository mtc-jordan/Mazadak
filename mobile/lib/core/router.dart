import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'providers/auth_provider.dart';

/// Route paths.
abstract final class AppRoutes {
  static const splash     = '/';
  static const login      = '/login';
  static const otp        = '/otp';
  static const home       = '/home';
  static const search     = '/search';
  static const myAuctions = '/my-auctions';
  static const profile    = '/profile';
  static const listing    = '/listing/:id';
  static const auction    = '/auction/:id';
  static const escrow     = '/escrow/:id';
  static const createListing = '/create-listing';
  static const notifications = '/notifications';
  static const kyc        = '/kyc';
}

/// GoRouter provider with auth-based redirect.
final routerProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authProvider);

  return GoRouter(
    initialLocation: AppRoutes.splash,
    debugLogDiagnostics: false,

    redirect: (context, state) {
      final isAuth = authState.status == AuthStatus.authenticated;
      final isOnAuth = state.matchedLocation == AppRoutes.login ||
          state.matchedLocation == AppRoutes.otp;
      final isOnSplash = state.matchedLocation == AppRoutes.splash;

      // Still loading — stay on splash
      if (authState.status == AuthStatus.unknown) {
        return isOnSplash ? null : AppRoutes.splash;
      }

      // Not authenticated — force to login
      if (!isAuth && !isOnAuth) {
        return AppRoutes.login;
      }

      // Authenticated but on auth screen — go home
      if (isAuth && (isOnAuth || isOnSplash)) {
        return AppRoutes.home;
      }

      return null;
    },

    routes: [
      // ── Splash ─────────────────────────────────────────────────
      GoRoute(
        path: AppRoutes.splash,
        builder: (_, __) => const _PlaceholderScreen('Splash'),
      ),

      // ── Auth flow ──────────────────────────────────────────────
      GoRoute(
        path: AppRoutes.login,
        builder: (_, __) => const _PlaceholderScreen('Login'),
      ),
      GoRoute(
        path: AppRoutes.otp,
        builder: (_, __) => const _PlaceholderScreen('OTP'),
      ),

      // ── Main shell with bottom nav ─────────────────────────────
      ShellRoute(
        builder: (context, state, child) => _ShellScaffold(child: child),
        routes: [
          GoRoute(
            path: AppRoutes.home,
            pageBuilder: (_, __) => const NoTransitionPage(
              child: _PlaceholderScreen('Home'),
            ),
          ),
          GoRoute(
            path: AppRoutes.search,
            pageBuilder: (_, __) => const NoTransitionPage(
              child: _PlaceholderScreen('Search'),
            ),
          ),
          GoRoute(
            path: AppRoutes.myAuctions,
            pageBuilder: (_, __) => const NoTransitionPage(
              child: _PlaceholderScreen('My Auctions'),
            ),
          ),
          GoRoute(
            path: AppRoutes.profile,
            pageBuilder: (_, __) => const NoTransitionPage(
              child: _PlaceholderScreen('Profile'),
            ),
          ),
        ],
      ),

      // ── Detail screens ─────────────────────────────────────────
      GoRoute(
        path: AppRoutes.listing,
        builder: (_, state) => _PlaceholderScreen(
          'Listing ${state.pathParameters["id"]}',
        ),
      ),
      GoRoute(
        path: AppRoutes.auction,
        builder: (_, state) => _PlaceholderScreen(
          'Auction ${state.pathParameters["id"]}',
        ),
      ),
      GoRoute(
        path: AppRoutes.escrow,
        builder: (_, state) => _PlaceholderScreen(
          'Escrow ${state.pathParameters["id"]}',
        ),
      ),
      GoRoute(
        path: AppRoutes.createListing,
        builder: (_, __) => const _PlaceholderScreen('Create Listing'),
      ),
      GoRoute(
        path: AppRoutes.notifications,
        builder: (_, __) => const _PlaceholderScreen('Notifications'),
      ),
      GoRoute(
        path: AppRoutes.kyc,
        builder: (_, __) => const _PlaceholderScreen('KYC'),
      ),
    ],
  );
});

// ── Placeholder widgets (replaced by actual screens later) ──────

class _PlaceholderScreen extends StatelessWidget {
  const _PlaceholderScreen(this.title);
  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(child: Text(title, style: Theme.of(context).textTheme.headlineMedium)),
    );
  }
}

class _ShellScaffold extends StatelessWidget {
  const _ShellScaffold({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final location = GoRouterState.of(context).matchedLocation;
    final index = switch (location) {
      AppRoutes.home       => 0,
      AppRoutes.search     => 1,
      AppRoutes.myAuctions => 2,
      AppRoutes.profile    => 3,
      _                    => 0,
    };

    return Scaffold(
      body: child,
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: index,
        onTap: (i) {
          final route = switch (i) {
            0 => AppRoutes.home,
            1 => AppRoutes.search,
            2 => AppRoutes.myAuctions,
            3 => AppRoutes.profile,
            _ => AppRoutes.home,
          };
          GoRouter.of(context).go(route);
        },
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home_rounded), label: 'الرئيسية'),
          BottomNavigationBarItem(icon: Icon(Icons.search_rounded), label: 'بحث'),
          BottomNavigationBarItem(icon: Icon(Icons.gavel_rounded), label: 'مزاداتي'),
          BottomNavigationBarItem(icon: Icon(Icons.person_rounded), label: 'حسابي'),
        ],
      ),
    );
  }
}
