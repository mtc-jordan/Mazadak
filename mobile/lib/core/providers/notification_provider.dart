import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core_providers.dart';

/// In-app notification model.
class AppNotification {
  const AppNotification({
    required this.id,
    required this.titleAr,
    required this.titleEn,
    required this.bodyAr,
    required this.bodyEn,
    required this.isRead,
    required this.createdAt,
    this.payload,
  });

  final String id;
  final String titleAr;
  final String titleEn;
  final String bodyAr;
  final String bodyEn;
  final bool isRead;
  final String createdAt;
  final Map<String, dynamic>? payload;

  factory AppNotification.fromJson(Map<String, dynamic> json) =>
      AppNotification(
        id: json['id'] as String,
        titleAr: json['title_ar'] as String? ?? '',
        titleEn: json['title_en'] as String? ?? '',
        bodyAr: json['body_ar'] as String? ?? '',
        bodyEn: json['body_en'] as String? ?? '',
        isRead: json['is_read'] as bool? ?? false,
        createdAt: json['created_at'] as String? ?? '',
        payload: json['payload'] as Map<String, dynamic>?,
      );
}

class NotificationState {
  const NotificationState({
    this.notifications = const [],
    this.unreadCount = 0,
    this.isLoading = false,
    this.error,
  });

  final List<AppNotification> notifications;
  final int unreadCount;
  final bool isLoading;
  final String? error;

  NotificationState copyWith({
    List<AppNotification>? notifications,
    int? unreadCount,
    bool? isLoading,
    String? error,
  }) => NotificationState(
        notifications: notifications ?? this.notifications,
        unreadCount: unreadCount ?? this.unreadCount,
        isLoading: isLoading ?? this.isLoading,
        error: error,
      );
}

/// Notification provider — SDD §7.1 notificationProvider.
///
/// Fetches in-app notifications and manages read state.
final notificationProvider =
    StateNotifierProvider<NotificationNotifier, NotificationState>((ref) {
  return NotificationNotifier(ref);
});

class NotificationNotifier extends StateNotifier<NotificationState> {
  NotificationNotifier(this._ref) : super(const NotificationState());

  final Ref _ref;

  Future<void> loadNotifications() async {
    state = state.copyWith(isLoading: true, error: null);
    try {
      final api = _ref.read(apiClientProvider);
      final resp = await api.get('/notifications');
      final data = resp.data as Map<String, dynamic>;

      final items = (data['notifications'] as List)
          .map((e) => AppNotification.fromJson(e as Map<String, dynamic>))
          .toList();

      state = NotificationState(
        notifications: items,
        unreadCount: data['unread_count'] as int? ?? 0,
      );
    } catch (e) {
      state = state.copyWith(isLoading: false, error: e.toString());
    }
  }

  Future<void> markAsRead(List<String> ids) async {
    try {
      final api = _ref.read(apiClientProvider);
      await api.post('/notifications/read', data: {'notification_ids': ids});

      state = state.copyWith(
        notifications: state.notifications.map((n) {
          if (ids.contains(n.id)) {
            return AppNotification(
              id: n.id,
              titleAr: n.titleAr,
              titleEn: n.titleEn,
              bodyAr: n.bodyAr,
              bodyEn: n.bodyEn,
              isRead: true,
              createdAt: n.createdAt,
              payload: n.payload,
            );
          }
          return n;
        }).toList(),
        unreadCount: (state.unreadCount - ids.length).clamp(0, state.unreadCount),
      );
    } catch (_) {
      // Non-critical — will sync on next load
    }
  }

  Future<void> markAllAsRead() async {
    final unreadIds = state.notifications
        .where((n) => !n.isRead)
        .map((n) => n.id)
        .toList();
    if (unreadIds.isNotEmpty) {
      await markAsRead(unreadIds);
    }
  }
}
