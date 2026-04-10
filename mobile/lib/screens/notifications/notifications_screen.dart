import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shimmer/shimmer.dart';

import '../../core/providers/notification_provider.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/spacing.dart';

// ══════════════════════════════════════════════════════════════════
// Filter types
// ══════════════════════════════════════════════════════════════════

enum _NotifFilter { all, bids, escrow, system, promotions }

extension on _NotifFilter {
  String get label => switch (this) {
        _NotifFilter.all => 'All',
        _NotifFilter.bids => 'Bids',
        _NotifFilter.escrow => 'Escrow',
        _NotifFilter.system => 'System',
        _NotifFilter.promotions => 'Promotions',
      };
}

/// Derive category from notification payload or title.
_NotifFilter _categoryOf(AppNotification n) {
  final type = n.payload?['type'] as String? ?? '';
  final title = n.titleEn.toLowerCase();

  if (type.startsWith('bid') ||
      title.contains('bid') ||
      title.contains('outbid') ||
      title.contains('leading')) {
    return _NotifFilter.bids;
  }
  if (type.startsWith('escrow') ||
      title.contains('escrow') ||
      title.contains('payment') ||
      title.contains('shipping') ||
      title.contains('delivery')) {
    return _NotifFilter.escrow;
  }
  if (type.startsWith('promo') || title.contains('promo') || title.contains('offer')) {
    return _NotifFilter.promotions;
  }
  return _NotifFilter.system;
}

/// Icon + color per category.
(IconData, Color) _iconFor(AppNotification n) {
  final cat = _categoryOf(n);
  final title = n.titleEn.toLowerCase();

  if (cat == _NotifFilter.bids) {
    // bid/outbid/leading → navy
    if (title.contains('outbid')) {
      return (Icons.arrow_upward_rounded, AppColors.navy);
    }
    if (title.contains('leading') || title.contains('winning') || title.contains('won')) {
      return (Icons.emoji_events_rounded, AppColors.navy);
    }
    return (Icons.gavel_rounded, AppColors.navy);
  }
  if (cat == _NotifFilter.escrow) {
    // escrow/payment → gold
    return (Icons.shield_rounded, AppColors.gold);
  }
  if (title.contains('dispute')) {
    // dispute → ember
    return (Icons.gavel_rounded, AppColors.ember);
  }
  if (title.contains('verified') || title.contains('success') || title.contains('approved')) {
    // success/verified → emerald
    return (Icons.check_circle_rounded, AppColors.emerald);
  }
  if (cat == _NotifFilter.promotions) {
    return (Icons.local_offer_rounded, AppColors.gold);
  }
  // system → mist
  return (Icons.info_outline_rounded, AppColors.mist);
}

// ══════════════════════════════════════════════════════════════════
// Screen
// ══════════════════════════════════════════════════════════════════

class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() =>
      _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  _NotifFilter _filter = _NotifFilter.all;
  final _listKey = GlobalKey<AnimatedListState>();

  /// Track deleted IDs so we can exclude them from the list.
  final Set<String> _deletedIds = {};

  @override
  void initState() {
    super.initState();
    // Load notifications on first open
    Future.microtask(
      () => ref.read(notificationProvider.notifier).loadNotifications(),
    );
  }

  List<AppNotification> _filtered(List<AppNotification> all) {
    final visible = all.where((n) => !_deletedIds.contains(n.id));
    if (_filter == _NotifFilter.all) return visible.toList();
    return visible.where((n) => _categoryOf(n) == _filter).toList();
  }

  // ── Grouping helpers ─────────────────────────────────────────

  /// Group notifications by day section.
  List<_ListEntry> _grouped(List<AppNotification> items) {
    final entries = <_ListEntry>[];
    String? lastSection;

    for (final n in items) {
      final section = _sectionLabel(n.createdAt);
      if (section != lastSection) {
        entries.add(_ListEntry.header(section));
        lastSection = section;
      }
      entries.add(_ListEntry.item(n));
    }
    return entries;
  }

  String _sectionLabel(String iso) {
    final dt = DateTime.tryParse(iso);
    if (dt == null) return 'Earlier';
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(dt.year, dt.month, dt.day);
    final diff = today.difference(day).inDays;

    if (diff == 0) return 'Today';
    if (diff == 1) return 'Yesterday';
    if (diff <= 7) return 'This week';
    return 'Earlier';
  }

  // ── Actions ──────────────────────────────────────────────────

  void _markRead(AppNotification n) {
    if (!n.isRead) {
      ref.read(notificationProvider.notifier).markAsRead([n.id]);
    }
  }

  void _markAllRead() {
    ref.read(notificationProvider.notifier).markAllAsRead();
  }

  void _delete(AppNotification n) {
    setState(() => _deletedIds.add(n.id));
    ref.read(notificationProvider.notifier).deleteNotification(n.id);
  }

  void _navigate(AppNotification n) {
    _markRead(n);
    final payload = n.payload;
    if (payload == null) return;

    final type = payload['type'] as String? ?? '';
    final id = payload['resource_id'] as String?;
    if (id == null) return;

    if (type.startsWith('bid') || type.contains('auction')) {
      context.push('/auction/$id');
    } else if (type.startsWith('escrow')) {
      context.push('/escrow/$id');
    } else if (type.contains('listing')) {
      context.push('/listing/$id');
    }
  }

  void _showOptions(AppNotification n) {
    showModalBottomSheet(
      context: context,
      builder: (_) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (!n.isRead)
              ListTile(
                leading: const Icon(Icons.mark_email_read_rounded,
                    color: AppColors.navy),
                title: const Text('Mark as read'),
                onTap: () {
                  Navigator.pop(context);
                  _markRead(n);
                },
              ),
            ListTile(
              leading:
                  const Icon(Icons.delete_outline_rounded, color: AppColors.ember),
              title: const Text('Delete'),
              onTap: () {
                Navigator.pop(context);
                _delete(n);
              },
            ),
          ],
        ),
      ),
    );
  }

  // ── Build ────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(notificationProvider);
    final hasUnread = state.unreadCount > 0;
    final items = _filtered(state.notifications);
    final entries = _grouped(items);

    return Scaffold(
      backgroundColor: AppColors.cream,
      appBar: AppBar(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        title: const Column(
          children: [
            Text(
              'Notifications',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w600,
              ),
            ),
            Text(
              'الإشعارات',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w400),
            ),
          ],
        ),
        centerTitle: true,
        actions: [
          if (hasUnread)
            TextButton(
              onPressed: _markAllRead,
              child: const Text(
                'Mark all read',
                style: TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: AppColors.gold,
                ),
              ),
            ),
        ],
      ),
      body: Column(
        children: [
          // Filter chips
          _FilterChips(
            selected: _filter,
            onChanged: (f) => setState(() => _filter = f),
          ),

          // Content
          Expanded(
            child: _buildBody(state, entries),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(NotificationState state, List<_ListEntry> entries) {
    // Loading skeleton
    if (state.isLoading && state.notifications.isEmpty) {
      return const _SkeletonList();
    }

    // Empty
    if (entries.isEmpty) {
      return const _EmptyState();
    }

    return RefreshIndicator(
      color: AppColors.navy,
      onRefresh: () =>
          ref.read(notificationProvider.notifier).loadNotifications(),
      child: AnimatedList(
        key: _listKey,
        padding: const EdgeInsets.only(bottom: AppSpacing.xxxl),
        initialItemCount: entries.length,
        itemBuilder: (context, i, animation) {
          if (i >= entries.length) return const SizedBox.shrink();
          final entry = entries[i];
          if (entry.isHeader) {
            return _SectionHeader(label: entry.headerLabel!);
          }
          return SizeTransition(
            sizeFactor: animation,
            child: _NotificationRow(
              notification: entry.notification!,
              onTap: () => _navigate(entry.notification!),
              onDismissed: () {
                final removedEntry = entries[i];
                _listKey.currentState?.removeItem(
                  i,
                  (context, anim) => SlideTransition(
                    position: Tween<Offset>(
                      begin: const Offset(1, 0),
                      end: Offset.zero,
                    ).animate(anim),
                    child: _NotificationRow(
                      notification: removedEntry.notification!,
                      onTap: () {},
                      onDismissed: () {},
                      onLongPress: () {},
                      onReadDot: () {},
                    ),
                  ),
                  duration: const Duration(milliseconds: 300),
                );
                _delete(entry.notification!);
              },
              onLongPress: () => _showOptions(entry.notification!),
              onReadDot: () => _markRead(entry.notification!),
            ),
          );
        },
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// List entry (header or item)
// ══════════════════════════════════════════════════════════════════

class _ListEntry {
  const _ListEntry.header(this.headerLabel)
      : notification = null,
        isHeader = true;
  const _ListEntry.item(this.notification)
      : headerLabel = null,
        isHeader = false;

  final String? headerLabel;
  final AppNotification? notification;
  final bool isHeader;
}

// ══════════════════════════════════════════════════════════════════
// Filter Chips
// ══════════════════════════════════════════════════════════════════

class _FilterChips extends StatelessWidget {
  const _FilterChips({
    required this.selected,
    required this.onChanged,
  });

  final _NotifFilter selected;
  final ValueChanged<_NotifFilter> onChanged;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 48,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.md,
          vertical: AppSpacing.xs,
        ),
        itemCount: _NotifFilter.values.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.xs),
        itemBuilder: (_, i) {
          final filter = _NotifFilter.values[i];
          final isActive = filter == selected;

          return GestureDetector(
            onTap: () => onChanged(filter),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              curve: Curves.easeOutCubic,
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
              decoration: BoxDecoration(
                color: isActive ? AppColors.navy : AppColors.cream,
                borderRadius: BorderRadius.circular(20),
                border: isActive
                    ? null
                    : Border.all(color: AppColors.sand, width: 1),
              ),
              child: Center(
                child: Text(
                  filter.label,
                  style: TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: isActive ? Colors.white : AppColors.mist,
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Section Header
// ══════════════════════════════════════════════════════════════════

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsetsDirectional.only(
        start: AppSpacing.md,
        top: AppSpacing.md,
        bottom: AppSpacing.xs,
      ),
      child: Text(
        label,
        style: const TextStyle(
          fontFamily: 'Sora',
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: AppColors.mist,
          letterSpacing: 0.5,
        ),
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Notification Row
// ══════════════════════════════════════════════════════════════════

class _NotificationRow extends StatefulWidget {
  const _NotificationRow({
    required this.notification,
    required this.onTap,
    required this.onDismissed,
    required this.onLongPress,
    required this.onReadDot,
  });

  final AppNotification notification;
  final VoidCallback onTap;
  final VoidCallback onDismissed;
  final VoidCallback onLongPress;
  final VoidCallback onReadDot;

  @override
  State<_NotificationRow> createState() => _NotificationRowState();
}

class _NotificationRowState extends State<_NotificationRow>
    with SingleTickerProviderStateMixin {
  late final AnimationController _dotFadeController;
  late final Animation<double> _dotOpacity;
  bool _localRead = false;

  @override
  void initState() {
    super.initState();
    _localRead = widget.notification.isRead;
    _dotFadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _dotOpacity = Tween(begin: 1.0, end: 0.0).animate(
      CurvedAnimation(parent: _dotFadeController, curve: Curves.easeOut),
    );
  }

  @override
  void didUpdateWidget(_NotificationRow old) {
    super.didUpdateWidget(old);
    if (!old.notification.isRead && widget.notification.isRead) {
      _fadeDot();
    }
  }

  @override
  void dispose() {
    _dotFadeController.dispose();
    super.dispose();
  }

  void _fadeDot() {
    if (!_localRead) {
      setState(() => _localRead = true);
      _dotFadeController.forward();
    }
  }

  void _onTap() {
    _fadeDot();
    widget.onReadDot();
    widget.onTap();
  }

  @override
  Widget build(BuildContext context) {
    final n = widget.notification;
    final isUnread = !n.isRead && !_localRead;
    final (icon, iconBg) = _iconFor(n);
    final fog = const Color(0xFFF5F2EC);

    return Dismissible(
      key: ValueKey(n.id),
      direction: DismissDirection.endToStart,
      onDismissed: (_) => widget.onDismissed(),
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsetsDirectional.only(end: AppSpacing.lg),
        color: AppColors.ember,
        child: const Icon(Icons.delete_rounded, color: Colors.white, size: 24),
      ),
      child: GestureDetector(
        onTap: _onTap,
        onLongPress: widget.onLongPress,
        behavior: HitTestBehavior.opaque,
        child: Container(
          color: isUnread ? Colors.white : fog,
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.md,
            vertical: AppSpacing.sm,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Icon circle
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: iconBg.withOpacity(0.15),
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: 20, color: iconBg),
              ),
              const SizedBox(width: AppSpacing.sm),

              // Text content
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      n.titleEn,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: isUnread ? AppColors.ink : AppColors.mist,
                      ),
                    ),
                    if (n.bodyEn.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        n.bodyEn,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppColors.mist,
                          height: 1.3,
                        ),
                      ),
                    ],
                    const SizedBox(height: 3),
                    Text(
                      _formatTime(n.createdAt),
                      style: const TextStyle(
                        fontSize: 10,
                        color: AppColors.mist,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpacing.xs),

              // Unread dot
              SizedBox(
                width: 12,
                height: 40,
                child: isUnread || _dotFadeController.isAnimating
                    ? Center(
                        child: FadeTransition(
                          opacity: _dotOpacity,
                          child: Container(
                            width: 8,
                            height: 8,
                            decoration: const BoxDecoration(
                              color: AppColors.navy,
                              shape: BoxShape.circle,
                            ),
                          ),
                        ),
                      )
                    : const SizedBox.shrink(),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _formatTime(String iso) {
    final dt = DateTime.tryParse(iso);
    if (dt == null) return '';
    final diff = DateTime.now().difference(dt);

    if (diff.inMinutes < 1) return 'Just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays == 1) return 'Yesterday';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return '${dt.day}/${dt.month}/${dt.year}';
  }
}

// ══════════════════════════════════════════════════════════════════
// Skeleton list
// ══════════════════════════════════════════════════════════════════

class _SkeletonList extends StatelessWidget {
  const _SkeletonList();

  @override
  Widget build(BuildContext context) {
    return Shimmer.fromColors(
      baseColor: AppColors.sand,
      highlightColor: AppColors.cream,
      child: ListView.builder(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.only(top: AppSpacing.md),
        itemCount: 8,
        itemBuilder: (_, __) => const _SkeletonRow(),
      ),
    );
  }
}

class _SkeletonRow extends StatelessWidget {
  const _SkeletonRow();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.xs,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Circle
          Container(
            width: 40,
            height: 40,
            decoration: const BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Title
                Container(
                  width: double.infinity,
                  height: 13,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: AppSpacing.radiusSm,
                  ),
                ),
                const SizedBox(height: 6),
                // Body line 1
                Container(
                  width: 200,
                  height: 11,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: AppSpacing.radiusSm,
                  ),
                ),
                const SizedBox(height: 4),
                // Body line 2
                Container(
                  width: 140,
                  height: 11,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: AppSpacing.radiusSm,
                  ),
                ),
                const SizedBox(height: 6),
                // Time
                Container(
                  width: 50,
                  height: 10,
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: AppSpacing.radiusSm,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.xs),
          // Dot placeholder
          Container(
            width: 8,
            height: 8,
            margin: const EdgeInsets.only(top: 16),
            decoration: const BoxDecoration(
              color: Colors.white,
              shape: BoxShape.circle,
            ),
          ),
        ],
      ),
    );
  }
}

// ══════════════════════════════════════════════════════════════════
// Empty state — bell illustration
// ══════════════════════════════════════════════════════════════════

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: AppSpacing.allXl,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Bell illustration with Flutter shapes
            SizedBox(
              width: 96,
              height: 96,
              child: CustomPaint(painter: _BellPainter()),
            ),
            const SizedBox(height: AppSpacing.lg),
            const Text(
              'No notifications yet',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 16,
                fontWeight: FontWeight.w700,
                color: AppColors.navy,
              ),
            ),
            const SizedBox(height: 4),
            const Text(
              'لا توجد إشعارات بعد',
              style: TextStyle(fontSize: 14, color: AppColors.mist),
              textDirection: TextDirection.rtl,
            ),
            const SizedBox(height: AppSpacing.sm),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: AppSpacing.xl),
              child: Text(
                "We'll notify you about bids, escrow updates, and more",
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 13,
                  color: AppColors.mist,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Bell illustration using Flutter shapes.
class _BellPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final h = size.height;

    // Body fill
    final bodyPaint = Paint()
      ..color = AppColors.sand
      ..style = PaintingStyle.fill;

    // Bell body path
    final body = Path()
      ..moveTo(cx - 28, h * 0.72)
      ..quadraticBezierTo(cx - 28, h * 0.35, cx - 14, h * 0.22)
      ..quadraticBezierTo(cx, h * 0.15, cx, h * 0.15)
      ..quadraticBezierTo(cx, h * 0.15, cx + 14, h * 0.22)
      ..quadraticBezierTo(cx + 28, h * 0.35, cx + 28, h * 0.72)
      ..lineTo(cx + 34, h * 0.78)
      ..lineTo(cx - 34, h * 0.78)
      ..close();
    canvas.drawPath(body, bodyPaint);

    // Bell rim
    final rimPaint = Paint()
      ..color = AppColors.mist.withOpacity(0.4)
      ..style = PaintingStyle.fill;
    final rim = RRect.fromRectAndRadius(
      Rect.fromCenter(center: Offset(cx, h * 0.78), width: 72, height: 6),
      const Radius.circular(3),
    );
    canvas.drawRRect(rim, rimPaint);

    // Clapper
    canvas.drawCircle(
      Offset(cx, h * 0.88),
      5,
      Paint()..color = AppColors.gold,
    );

    // Top knob
    canvas.drawCircle(
      Offset(cx, h * 0.13),
      4,
      Paint()..color = AppColors.mist.withOpacity(0.5),
    );

    // Notification badge (small red dot top-right)
    canvas.drawCircle(
      Offset(cx + 18, h * 0.2),
      6,
      Paint()..color = AppColors.ember,
    );
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
