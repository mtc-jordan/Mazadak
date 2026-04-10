import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../main.dart' show navigatorKey;

import '../features/auction/auction_room_screen.dart';
import '../features/escrow/escrow_order_screen.dart';
import '../features/listing/create_listing_screen.dart';
import '../screens/auction/live_video_auction_screen.dart';
import '../screens/b2b/tender_room_screen.dart';
import '../screens/buyer/my_bids_screen.dart';
import '../screens/escrow/dispute_screen.dart';
import '../screens/listing_detail_screen.dart';
import '../screens/settings/settings_screen.dart';
import '../screens/settings/whatsapp_bot_screen.dart';
import '../screens/notifications/notifications_screen.dart';
import '../screens/charity/charity_screen.dart';
import '../screens/seller/my_auctions_screen.dart';
import '../screens/seller/my_listings_screen.dart';
import '../screens/snap_to_list_screen.dart';
import '../screens/auth/kyc_screen.dart';
import '../screens/auth/otp_verification_screen.dart';
import '../screens/auth/phone_registration_screen.dart';
import '../screens/auth/splash_screen.dart';
import '../screens/auth/welcome_screen.dart';
import '../screens/home/home_screen.dart';
import '../screens/search/search_screen.dart';
import 'providers/auth_provider.dart';
import 'router/transitions.dart';
import 'theme/colors.dart';

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
  static const welcome   = '/welcome';
  static const liveAuction = '/live-auction/:id';
  static const dispute     = '/escrow/:id/dispute';
  static const myListings  = '/my-listings';
  static const myBids      = '/my-bids';
  static const snapToList = '/snap-to-list';
  static const charity    = '/charity';
  static const whatsappBot = '/whatsapp-bot';
  static const tenderRoom  = '/tender/:id';
}

/// Hero tag builders — use these in listing cards and detail screens
/// to keep tags consistent across routes.
abstract final class HeroTags {
  /// Hero tag for listing card image → detail header image.
  static String listingImage(String id) => 'listing-image-$id';

  /// Hero tag for price display flying from listing → auction room.
  static String price(String id) => 'price-$id';
}

/// GoRouter provider with auth-based redirect and custom page transitions.
final routerProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authProvider);

  return GoRouter(
    navigatorKey: navigatorKey,
    initialLocation: AppRoutes.splash,
    debugLogDiagnostics: false,

    redirect: (context, state) {
      final isAuth = authState.status == AuthStatus.authenticated;
      final isOnAuth = state.matchedLocation == AppRoutes.login ||
          state.matchedLocation == AppRoutes.otp;
      final isOnSplash = state.matchedLocation == AppRoutes.splash;
      final isOnWelcome = state.matchedLocation == AppRoutes.welcome;

      // Still loading — stay on splash
      if (authState.status == AuthStatus.unknown) {
        return isOnSplash ? null : AppRoutes.splash;
      }

      // Not authenticated — allow welcome, force others to login
      if (!isAuth && !isOnAuth && !isOnWelcome) {
        return AppRoutes.login;
      }

      // Authenticated but on auth/welcome screen — route by KYC status
      if (isAuth && (isOnAuth || isOnSplash || isOnWelcome)) {
        final kyc = authState.kycStatus;
        if (kyc == null || kyc == 'not_started' || kyc == 'pending') {
          return AppRoutes.kyc;
        }
        return AppRoutes.home;
      }

      return null;
    },

    routes: [
      // ── Splash: logo scale-in (400ms spring) ─────────────────
      GoRoute(
        path: AppRoutes.splash,
        pageBuilder: (_, __) => FadeScaleTransitionPage(
          child: const SplashScreen(),
        ),
      ),

      // ── Welcome: staggered cards + sheet spring ────────────────
      GoRoute(
        path: AppRoutes.welcome,
        pageBuilder: (_, __) => FadeScaleTransitionPage(
          child: const WelcomeScreen(),
        ),
      ),

      // ── Auth flow ──────────────────────────────────────────────
      GoRoute(
        path: AppRoutes.login,
        pageBuilder: (_, __) => FadeScaleTransitionPage(
          child: const PhoneRegistrationScreen(),
        ),
      ),
      GoRoute(
        path: AppRoutes.otp,
        pageBuilder: (_, state) {
          final phone = state.extra as String? ?? '';
          return DimmedSlideFromBottomPage(
            child: OtpVerificationScreen(phoneNumber: phone),
          );
        },
      ),

      // ── Main shell with bottom nav ─────────────────────────────
      // Tab switching: instant with 80ms subtle fade.
      ShellRoute(
        builder: (context, state, child) => _ShellScaffold(child: child),
        routes: [
          GoRoute(
            path: AppRoutes.home,
            pageBuilder: (_, __) => SubtleFadePage(
              child: const HomeScreen(),
            ),
          ),
          GoRoute(
            path: AppRoutes.search,
            pageBuilder: (_, __) => SubtleFadePage(
              child: const SearchScreen(),
            ),
          ),
          GoRoute(
            path: AppRoutes.myAuctions,
            pageBuilder: (_, __) => SubtleFadePage(
              child: const MyAuctionsScreen(),
            ),
          ),
          // Profile: FadeScaleTransition — like zooming into settings
          GoRoute(
            path: AppRoutes.profile,
            pageBuilder: (_, __) => FadeScaleTransitionPage(
              child: const SettingsScreen(),
            ),
          ),
        ],
      ),

      // ── Detail screens ─────────────────────────────────────────

      // Home → Listing: Hero animation on card image + fade/slide up 16px/350ms.
      // Uses HeroSlideUpTransitionPage (opaque: false) so the Hero
      // on listing-image-$id flies to the full-width header.
      GoRoute(
        path: AppRoutes.listing,
        pageBuilder: (_, state) {
          final id = state.pathParameters['id']!;
          return HeroSlideUpTransitionPage(
            child: ListingDetailScreen(listingId: id),
          );
        },
      ),

      // Listing → Auction: AuctionHeroTransitionPage (SharedAxis horizontal
      // + Hero layer for price flying from listing → LivePriceDisplay).
      GoRoute(
        path: AppRoutes.auction,
        pageBuilder: (_, state) {
          final id = state.pathParameters['id']!;
          return AuctionHeroTransitionPage(
            child: AuctionRoomScreen(auctionId: id),
          );
        },
      ),

      // Live Video Auction: FadeScale (immersive full-screen)
      GoRoute(
        path: AppRoutes.liveAuction,
        pageBuilder: (_, state) {
          final id = state.pathParameters['id']!;
          return FadeScaleTransitionPage(
            child: LiveVideoAuctionScreen(auctionId: id),
          );
        },
      ),

      // Escrow: SlideUp
      GoRoute(
        path: AppRoutes.escrow,
        pageBuilder: (_, state) => SlideUpTransitionPage(
          child: EscrowOrderScreen(
            escrowId: state.pathParameters['id']!,
          ),
        ),
      ),

      // Dispute: SlideUp from EscrowOrderScreen
      GoRoute(
        path: AppRoutes.dispute,
        pageBuilder: (_, state) {
          final id = state.pathParameters['id']!;
          return SlideUpTransitionPage(
            child: DisputeScreen(escrowId: id),
          );
        },
      ),

      // Create listing: DimmedSlideFromBottom (modal-style with dim background)
      GoRoute(
        path: AppRoutes.createListing,
        pageBuilder: (_, __) => DimmedSlideFromBottomPage(
          child: const CreateListingScreen(),
        ),
      ),

      // My Listings: SubtleFade
      GoRoute(
        path: AppRoutes.myListings,
        pageBuilder: (_, __) => SubtleFadePage(
          child: const MyListingsScreen(),
        ),
      ),

      // My Bids: SubtleFade
      GoRoute(
        path: AppRoutes.myBids,
        pageBuilder: (_, __) => SubtleFadePage(
          child: const MyBidsScreen(),
        ),
      ),

      // Notifications: SlideUp
      GoRoute(
        path: AppRoutes.notifications,
        pageBuilder: (_, __) => SlideUpTransitionPage(
          child: const NotificationsScreen(),
        ),
      ),

      // KYC: FadeScale
      GoRoute(
        path: AppRoutes.kyc,
        pageBuilder: (_, __) => FadeScaleTransitionPage(
          child: const KycScreen(),
        ),
      ),

      // Snap-to-List: AI pipeline screen
      GoRoute(
        path: AppRoutes.snapToList,
        pageBuilder: (_, __) => FadeScaleTransitionPage(
          child: const SnapToListScreen(imageKeys: []),
        ),
      ),

      // Charity: FadeScale (immersive vertical)
      GoRoute(
        path: AppRoutes.charity,
        pageBuilder: (_, __) => FadeScaleTransitionPage(
          child: const CharityScreen(),
        ),
      ),

      // WhatsApp Bot: SlideUp from Settings
      GoRoute(
        path: AppRoutes.whatsappBot,
        pageBuilder: (_, __) => SlideUpTransitionPage(
          child: const WhatsappBotScreen(),
        ),
      ),

      // Tender Room: FadeScale (formal B2B context)
      GoRoute(
        path: AppRoutes.tenderRoom,
        pageBuilder: (_, state) {
          final id = state.pathParameters['id']!;
          return FadeScaleTransitionPage(
            child: TenderRoomScreen(tenderId: id),
          );
        },
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

  static const _navy2 = Color(0xFF152840);

  @override
  Widget build(BuildContext context) {
    final location = GoRouterState.of(context).matchedLocation;
    // 5-slot nav: 0=Home, 1=Browse, 2=Sell(center), 3=Saved, 4=Profile
    final index = switch (location) {
      AppRoutes.home       => 0,
      AppRoutes.search     => 1,
      AppRoutes.myAuctions => 3,
      AppRoutes.profile    => 4,
      _                    => 0,
    };

    return Scaffold(
      body: child,
      extendBody: true,
      bottomNavigationBar: _MzadakBottomNav(
        currentIndex: index,
        onTap: (i) {
          if (i == 2) {
            // Center sell button → Snap-to-List
            GoRouter.of(context).push(AppRoutes.snapToList);
            return;
          }
          final route = switch (i) {
            0 => AppRoutes.home,
            1 => AppRoutes.search,
            3 => AppRoutes.myAuctions,
            4 => AppRoutes.profile,
            _ => AppRoutes.home,
          };
          GoRouter.of(context).go(route);
        },
      ),
    );
  }
}

/// 5-tab bottom nav: Home, Browse, [+] Sell, Saved, Profile.
///
/// Center [+] is a gold circle elevated above the bar.
/// Active item: gold icon + gold dot below; inactive: white38.
/// Background: navy2 #152840.
class _MzadakBottomNav extends StatelessWidget {
  const _MzadakBottomNav({
    required this.currentIndex,
    required this.onTap,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;

  static const _navy2 = Color(0xFF152840);

  static const _items = [
    (icon: Icons.home_rounded, label: 'Home'),
    (icon: Icons.search_rounded, label: 'Browse'),
    (icon: Icons.add, label: ''), // placeholder — center button
    (icon: Icons.favorite_rounded, label: 'Saved'),
    (icon: Icons.person_rounded, label: 'Profile'),
  ];

  @override
  Widget build(BuildContext context) {
    final bottomPad = MediaQuery.of(context).padding.bottom;

    return Container(
      height: 60 + bottomPad,
      decoration: const BoxDecoration(color: _navy2),
      padding: EdgeInsets.only(bottom: bottomPad),
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          // Tab items
          Row(
            children: List.generate(5, (i) {
              if (i == 2) {
                // Spacer for center button
                return const Expanded(child: SizedBox());
              }
              final selected = i == currentIndex;
              return Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => onTap(i),
                  child: _NavItem(
                    icon: _items[i].icon,
                    label: _items[i].label,
                    isSelected: selected,
                  ),
                ),
              );
            }),
          ),

          // Center [+] sell button — elevated above bar
          Positioned(
            top: -8,
            left: 0,
            right: 0,
            child: Center(
              child: GestureDetector(
                onTap: () => onTap(2),
                child: Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: AppColors.gold,
                    shape: BoxShape.circle,
                    border: Border.all(color: _navy2, width: 3),
                    boxShadow: [
                      BoxShadow(
                        color: AppColors.gold.withOpacity(0.3),
                        blurRadius: 8,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: const Icon(
                    Icons.add_rounded,
                    color: Colors.white,
                    size: 26,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({
    required this.icon,
    required this.label,
    required this.isSelected,
  });

  final IconData icon;
  final String label;
  final bool isSelected;

  @override
  Widget build(BuildContext context) {
    return AnimatedOpacity(
      duration: const Duration(milliseconds: 80),
      opacity: 1.0,
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          TweenAnimationBuilder<double>(
            tween: Tween(end: isSelected ? 1.15 : 1.0),
            duration: const Duration(milliseconds: 300),
            curve: isSelected ? Curves.elasticOut : Curves.easeOut,
            builder: (_, scale, child) => Transform.scale(
              scale: scale,
              child: child,
            ),
            child: AnimatedSwitcher(
              duration: const Duration(milliseconds: 200),
              child: Icon(
                icon,
                key: ValueKey('$icon-$isSelected'),
                size: 22,
                color: isSelected ? AppColors.gold : Colors.white38,
              ),
            ),
          ),
          const SizedBox(height: 2),
          // Gold dot indicator
          AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            width: isSelected ? 4 : 0,
            height: isSelected ? 4 : 0,
            decoration: const BoxDecoration(
              color: AppColors.gold,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(height: 1),
          Text(
            label,
            style: TextStyle(
              fontSize: 8,
              fontWeight: FontWeight.w600,
              color: isSelected ? AppColors.gold : Colors.white38,
            ),
          ),
        ],
      ),
    );
  }
}
