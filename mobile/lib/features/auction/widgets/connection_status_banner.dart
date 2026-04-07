import 'package:flutter/material.dart';

import '../../../core/providers/auction_provider.dart';
import '../../../core/theme/animations.dart';
import '../../../core/theme/colors.dart';
import '../../../core/theme/spacing.dart';

/// Connection status banner that slides from top on disconnect.
///
/// SDD §7.2:
/// - Shows only on DISCONNECTED / RECONNECTING
/// - Amber warning color
/// - Auto-hides 2 seconds after reconnect
class ConnectionStatusBanner extends StatefulWidget {
  const ConnectionStatusBanner({
    super.key,
    required this.status,
  });

  final ConnectionStatus status;

  @override
  State<ConnectionStatusBanner> createState() => _ConnectionStatusBannerState();
}

class _ConnectionStatusBannerState extends State<ConnectionStatusBanner>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<Offset> _slideAnimation;
  bool _wasDisconnected = false;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: AppAnimations.enter,
    );
    _slideAnimation = Tween<Offset>(
      begin: const Offset(0, -1),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _controller,
      curve: AppAnimations.enterCurve,
      reverseCurve: AppAnimations.exitCurve,
    ));

    _updateVisibility();
  }

  @override
  void didUpdateWidget(ConnectionStatusBanner old) {
    super.didUpdateWidget(old);
    if (old.status != widget.status) {
      _updateVisibility();
    }
  }

  void _updateVisibility() {
    if (widget.status == ConnectionStatus.disconnected ||
        widget.status == ConnectionStatus.reconnecting) {
      _wasDisconnected = true;
      _controller.forward();
    } else if (widget.status == ConnectionStatus.connected && _wasDisconnected) {
      // Auto-hide after 2 seconds on reconnect
      Future.delayed(const Duration(seconds: 2), () {
        if (mounted && widget.status == ConnectionStatus.connected) {
          _controller.reverse();
          _wasDisconnected = false;
        }
      });
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String get _message => switch (widget.status) {
        ConnectionStatus.disconnected => 'انقطع الاتصال — جاري إعادة الاتصال...',
        ConnectionStatus.reconnecting => 'جاري إعادة الاتصال...',
        ConnectionStatus.connected    => 'تم إعادة الاتصال',
      };

  IconData get _icon => switch (widget.status) {
        ConnectionStatus.disconnected => Icons.wifi_off_rounded,
        ConnectionStatus.reconnecting => Icons.sync_rounded,
        ConnectionStatus.connected    => Icons.wifi_rounded,
      };

  Color get _bgColor => widget.status == ConnectionStatus.connected
      ? AppColors.emerald
      : const Color(0xFFFBE8A0); // amber warning

  Color get _fgColor => widget.status == ConnectionStatus.connected
      ? Colors.white
      : AppColors.gold;

  @override
  Widget build(BuildContext context) {
    return SlideTransition(
      position: _slideAnimation,
      child: AnimatedContainer(
        duration: AppAnimations.state,
        width: double.infinity,
        padding: EdgeInsetsDirectional.only(
          start: AppSpacing.md,
          end: AppSpacing.md,
          top: MediaQuery.of(context).viewPadding.top + AppSpacing.xs,
          bottom: AppSpacing.xs,
        ),
        color: _bgColor,
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(_icon, size: 16, color: _fgColor),
            const SizedBox(width: AppSpacing.xs),
            Text(
              _message,
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: _fgColor,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
