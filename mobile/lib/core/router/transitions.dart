import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../theme/animations.dart';

/// Custom page transitions for MZADAK go_router.

/// Returns -1.0 when the context is RTL, 1.0 when LTR.
/// Used to flip horizontal slide directions for Arabic layout.
double _rtlSign(BuildContext context) =>
    Directionality.of(context) == TextDirection.rtl ? -1.0 : 1.0;

// ── Hero-aware Slide Up Transition ──────────────────────────────────
/// Used for Home → Listing detail.
/// Hero animation on listing card image (extends to full-width header).
/// Card content fades + slides up 16px over 350ms.
/// [opaque] is false so Hero widgets can fly across routes.
class HeroSlideUpTransitionPage<T> extends CustomTransitionPage<T> {
  HeroSlideUpTransitionPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          opaque: false,
          transitionDuration: const Duration(milliseconds: 350),
          reverseTransitionDuration: const Duration(milliseconds: 250),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            // 16px slide up as fraction ≈ 0.02
            final slide = Tween<Offset>(
              begin: const Offset(0, 0.02),
              end: Offset.zero,
            ).animate(CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            ));

            final fade = CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            );

            return FadeTransition(
              opacity: fade,
              child: SlideTransition(
                position: slide,
                child: child,
              ),
            );
          },
        );
}

// ── Shared Axis Transition (horizontal) ─────────────────────────────
/// Used for Listing → Auction navigation.
/// Feels like going deeper into the content.
class SharedAxisTransitionPage<T> extends CustomTransitionPage<T> {
  SharedAxisTransitionPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          transitionDuration: AppAnimations.enter,
          reverseTransitionDuration: AppAnimations.state,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final sign = _rtlSign(context);

            // Primary: slide in from end + fade in
            final slideIn = Tween<Offset>(
              begin: Offset(0.25 * sign, 0),
              end: Offset.zero,
            ).animate(CurvedAnimation(
              parent: animation,
              curve: AppAnimations.sharedAxis,
            ));

            final fadeIn = Tween<double>(begin: 0, end: 1).animate(
              CurvedAnimation(
                parent: animation,
                curve: const Interval(0, 0.75, curve: Curves.easeOut),
              ),
            );

            // Secondary: slide out to start + fade out
            final slideOut = Tween<Offset>(
              begin: Offset.zero,
              end: Offset(-0.25 * sign, 0),
            ).animate(CurvedAnimation(
              parent: secondaryAnimation,
              curve: AppAnimations.sharedAxis,
            ));

            final fadeOut = Tween<double>(begin: 1, end: 0).animate(
              CurvedAnimation(
                parent: secondaryAnimation,
                curve: const Interval(0, 0.75, curve: Curves.easeIn),
              ),
            );

            return FadeTransition(
              opacity: fadeOut,
              child: SlideTransition(
                position: slideOut,
                child: FadeTransition(
                  opacity: fadeIn,
                  child: SlideTransition(
                    position: slideIn,
                    child: child,
                  ),
                ),
              ),
            );
          },
        );
}

// ── Auction Hero Transition ─────────────────────────────────────────
/// Custom PageRouteBuilder for Listing → Auction room.
/// Supports Hero (price hero flying from listing to auction display).
/// Uses SharedAxis horizontal + Hero layer.
class AuctionHeroTransitionPage<T> extends CustomTransitionPage<T> {
  AuctionHeroTransitionPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          opaque: false,
          transitionDuration: AppAnimations.enter,
          reverseTransitionDuration: const Duration(milliseconds: 300),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final sign = _rtlSign(context);

            // Shared-axis horizontal slide
            final slide = Tween<Offset>(
              begin: Offset(0.3 * sign, 0),
              end: Offset.zero,
            ).animate(CurvedAnimation(
              parent: animation,
              curve: AppAnimations.sharedAxis,
            ));

            // Fade in content (Hero layer flies independently)
            final fade = Tween<double>(begin: 0, end: 1).animate(
              CurvedAnimation(
                parent: animation,
                curve: const Interval(0.15, 0.85, curve: Curves.easeOut),
              ),
            );

            // Slight scale from 0.97 for depth feel
            final scale = Tween<double>(begin: 0.97, end: 1.0).animate(
              CurvedAnimation(
                parent: animation,
                curve: AppAnimations.sharedAxis,
              ),
            );

            return FadeTransition(
              opacity: fade,
              child: SlideTransition(
                position: slide,
                child: ScaleTransition(
                  scale: scale,
                  child: child,
                ),
              ),
            );
          },
        );
}

// ── Fade Scale Transition ───────────────────────────────────────────
/// Used for Profile / Settings screens — like zooming into settings.
class FadeScaleTransitionPage<T> extends CustomTransitionPage<T> {
  FadeScaleTransitionPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          transitionDuration: AppAnimations.state,
          reverseTransitionDuration: AppAnimations.state,
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final fade = CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            );

            final scale = Tween<double>(begin: 0.92, end: 1.0).animate(fade);

            return FadeTransition(
              opacity: fade,
              child: ScaleTransition(
                scale: scale,
                child: child,
              ),
            );
          },
        );
}

// ── Slide Up Transition ─────────────────────────────────────────────
/// Generic slide-up for detail screens without Hero needs.
class SlideUpTransitionPage<T> extends CustomTransitionPage<T> {
  SlideUpTransitionPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          transitionDuration: const Duration(milliseconds: 350),
          reverseTransitionDuration: const Duration(milliseconds: 250),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final slide = Tween<Offset>(
              begin: const Offset(0, 0.02),
              end: Offset.zero,
            ).animate(CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            ));

            final fade = CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            );

            return FadeTransition(
              opacity: fade,
              child: SlideTransition(
                position: slide,
                child: child,
              ),
            );
          },
        );
}

// ── Bottom Sheet Slide Transition with Dim ──────────────────────────
/// Custom SlideTransition from bottom with dimmed background scrim.
class DimmedSlideFromBottomPage<T> extends CustomTransitionPage<T> {
  DimmedSlideFromBottomPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          opaque: false,
          barrierColor: Colors.black54,
          barrierDismissible: true,
          transitionDuration: AppAnimations.enter,
          reverseTransitionDuration: const Duration(milliseconds: 300),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final slide = Tween<Offset>(
              begin: const Offset(0, 1),
              end: Offset.zero,
            ).animate(CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            ));

            return SlideTransition(position: slide, child: child);
          },
        );
}

// ── Bottom Sheet Slide Transition (opaque) ──────────────────────────
/// Full-screen modal-style slide from bottom.
class SlideFromBottomPage<T> extends CustomTransitionPage<T> {
  SlideFromBottomPage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          transitionDuration: AppAnimations.enter,
          reverseTransitionDuration: const Duration(milliseconds: 300),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final slide = Tween<Offset>(
              begin: const Offset(0, 1),
              end: Offset.zero,
            ).animate(CurvedAnimation(
              parent: animation,
              curve: AppAnimations.enterCurve,
              reverseCurve: AppAnimations.exitCurve,
            ));

            return SlideTransition(position: slide, child: child);
          },
        );
}

// ── Subtle Fade Transition ──────────────────────────────────────────
/// Used for bottom nav tab switching — instant with 80ms subtle fade.
class SubtleFadePage<T> extends CustomTransitionPage<T> {
  SubtleFadePage({
    required super.child,
    super.key,
    super.name,
  }) : super(
          transitionDuration: const Duration(milliseconds: 80),
          reverseTransitionDuration: const Duration(milliseconds: 80),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            return FadeTransition(opacity: animation, child: child);
          },
        );
}
