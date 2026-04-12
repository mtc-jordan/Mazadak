import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/l10n/arabic_numerals.dart';
import '../../core/providers/auction_provider.dart';
import '../../core/theme/animations.dart';
import '../../core/theme/colors.dart';
import '../../core/theme/haptics.dart';
import '../../l10n/app_localizations.dart';

/// Premium live video auction screen.
///
/// Layout: full-screen dark (#0D0D1A), video top 55%, bidding UI bottom 45%.
/// Features: LiveKit video placeholder, pulsing LIVE badge, viewer count,
/// bids/chat tabs, compact bid input with quick chips, anti-snipe banner,
/// and connection status banners.
class LiveVideoAuctionScreen extends ConsumerStatefulWidget {
  const LiveVideoAuctionScreen({super.key, required this.auctionId});
  final String auctionId;

  @override
  ConsumerState<LiveVideoAuctionScreen> createState() =>
      _LiveVideoAuctionScreenState();
}

class _LiveVideoAuctionScreenState
    extends ConsumerState<LiveVideoAuctionScreen>
    with TickerProviderStateMixin {
  static const _dark = Color(0xFF0D0D1A);
  static const _navy2 = Color(0xFF152840);

  int _tabIndex = 0; // 0 = Bids, 1 = Chat
  bool _isMuted = false;
  bool _isFullscreen = false;
  bool _hasVideoSignal = false; // simulated
  int _viewerCount = 247;

  // ── Chat state ──────────────────────────────────────────────────
  final _chatController = TextEditingController();
  final _chatMessages = <_ChatMessage>[];
  bool _showEmoji = false;

  // ── Bid input ───────────────────────────────────────────────────
  double _bidAmount = 0;

  // ── LIVE badge pulse ────────────────────────────────────────────
  late final AnimationController _livePulse;
  late final Animation<double> _livePulseOpacity;

  // ── Anti-snipe banner ───────────────────────────────────────────
  late final AnimationController _bannerController;
  late final Animation<Offset> _bannerSlide;

  // ── Tab underline ───────────────────────────────────────────────
  late final AnimationController _tabController;

  // ── Connection banner ───────────────────────────────────────────
  late final AnimationController _connBannerController;
  late final Animation<Offset> _connBannerSlide;

  @override
  void initState() {
    super.initState();

    // Immersive mode
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);

    // LIVE pulse: opacity 1→0.3→1, 1s loop
    _livePulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    );
    _livePulseOpacity = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 1.0, end: 0.3), weight: 50),
      TweenSequenceItem(tween: Tween(begin: 0.3, end: 1.0), weight: 50),
    ]).animate(_livePulse);
    _livePulse.repeat();

    // Anti-snipe banner: slides from top
    _bannerController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 300),
    );
    _bannerSlide = Tween<Offset>(
      begin: const Offset(0, -1),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _bannerController,
      curve: Curves.easeOutCubic,
    ));

    // Tab underline
    _tabController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 200),
    );

    // Connection banner
    _connBannerController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 250),
    );
    _connBannerSlide = Tween<Offset>(
      begin: const Offset(0, -1),
      end: Offset.zero,
    ).animate(CurvedAnimation(
      parent: _connBannerController,
      curve: Curves.easeOutCubic,
    ));

    // Simulate video signal arriving after 2s
    Future.delayed(const Duration(seconds: 2), () {
      if (mounted) setState(() => _hasVideoSignal = true);
    });
  }

  @override
  void dispose() {
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
    _livePulse.dispose();
    _bannerController.dispose();
    _tabController.dispose();
    _connBannerController.dispose();
    _chatController.dispose();
    super.dispose();
  }

  // ── Auction state listener ──────────────────────────────────────

  void _handleAuctionState(AuctionState? prev, AuctionState next) {
    // Init bid amount
    if (_bidAmount == 0 && next.currentPrice > 0) {
      _bidAmount = next.currentPrice + next.minIncrement;
    }

    // Anti-snipe banner
    if (next.timerExtended && !(prev?.timerExtended ?? false)) {
      _bannerController.forward(from: 0);
      Future.delayed(const Duration(seconds: 5), () {
        if (mounted) _bannerController.reverse();
      });
    }

    // Connection status banner
    if (next.connectionStatus == ConnectionStatus.disconnected ||
        next.connectionStatus == ConnectionStatus.reconnecting) {
      _connBannerController.forward();
    } else if (next.connectionStatus == ConnectionStatus.connected &&
        (prev?.connectionStatus != ConnectionStatus.connected)) {
      Future.delayed(const Duration(milliseconds: 500), () {
        if (mounted) _connBannerController.reverse();
      });
    }
  }

  // ── Build ───────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final auction = ref.watch(auctionProvider(widget.auctionId));

    ref.listen(auctionProvider(widget.auctionId), _handleAuctionState);

    if (_bidAmount == 0 && auction.currentPrice > 0) {
      _bidAmount = auction.currentPrice + auction.minIncrement;
    }

    return Scaffold(
      backgroundColor: _dark,
      body: Stack(
        children: [
          Column(
            children: [
              // ── Video area (55%) ───────────────────────────────
              Expanded(
                flex: 55,
                child: _buildVideoArea(auction),
              ),

              // ── Auction info strip ─────────────────────────────
              _AuctionInfoStrip(auction: auction),

              // ── Bid/Chat area (45%) ────────────────────────────
              Expanded(
                flex: 45,
                child: Container(
                  color: _navy2,
                  child: Column(
                    children: [
                      _buildTabRow(),
                      Expanded(
                        child: _tabIndex == 0
                            ? _BidsFeed(bids: auction.bids)
                            : _ChatFeed(
                                messages: _chatMessages,
                                controller: _chatController,
                                showEmoji: _showEmoji,
                                onSend: _sendChat,
                                onToggleEmoji: () => setState(
                                    () => _showEmoji = !_showEmoji),
                              ),
                      ),
                      _buildBidInput(auction),
                    ],
                  ),
                ),
              ),
            ],
          ),

          // ── Anti-snipe banner overlay ──────────────────────────
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SlideTransition(
              position: _bannerSlide,
              child: SafeArea(
                bottom: false,
                child: Container(
                  margin: const EdgeInsets.symmetric(
                      horizontal: 16, vertical: 4),
                  padding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: AppColors.navy,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                        color: AppColors.gold.withOpacity(0.3)),
                  ),
                  child: const Text(
                    'Extended 3 minutes! · تم تمديد الوقت!',
                    style: TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.gold,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ),
              ),
            ),
          ),

          // ── Connection status banner ───────────────────────────
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SlideTransition(
              position: _connBannerSlide,
              child: _ConnectionBanner(
                status: auction.connectionStatus,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── Video area ──────────────────────────────────────────────────

  Widget _buildVideoArea(AuctionState auction) {
    return Stack(
      fit: StackFit.expand,
      children: [
        // Video / placeholder
        InteractiveViewer(
          minScale: 1.0,
          maxScale: 3.0,
          child: _hasVideoSignal
              ? Container(
                  color: _dark,
                  // In production: LiveKit VideoView widget goes here.
                  // Placeholder: dark gradient simulating video.
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [
                          _dark,
                          _dark.withOpacity(0.7),
                        ],
                      ),
                    ),
                    child: const Center(
                      child: Icon(Icons.videocam_rounded,
                          color: Colors.white12, size: 64),
                    ),
                  ),
                )
              : _NoVideoPlaceholder(),
        ),

        // ── Overlay top-left: LIVE + viewers ─────────────────────
        Positioned(
          top: MediaQuery.of(context).padding.top + 8,
          left: 12,
          child: Row(
            children: [
              // LIVE badge
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.ember,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    AnimatedBuilder(
                      animation: _livePulseOpacity,
                      builder: (_, __) => Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: Colors.white
                              .withOpacity(_livePulseOpacity.value),
                          shape: BoxShape.circle,
                        ),
                      ),
                    ),
                    const SizedBox(width: 4),
                    const Text(
                      'LIVE',
                      style: TextStyle(
                        fontFamily: 'Sora',
                        fontSize: 9,
                        fontWeight: FontWeight.w800,
                        color: Colors.white,
                        letterSpacing: 1,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              // Viewer count
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.black45,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  '👁 $_viewerCount',
                  style: const TextStyle(
                    fontSize: 10,
                    fontWeight: FontWeight.w600,
                    color: Colors.white70,
                  ),
                ),
              ),
            ],
          ),
        ),

        // ── Overlay top-right: fullscreen + mute ─────────────────
        Positioned(
          top: MediaQuery.of(context).padding.top + 8,
          right: 12,
          child: Row(
            children: [
              _OverlayIconBtn(
                icon: _isFullscreen
                    ? Icons.fullscreen_exit_rounded
                    : Icons.fullscreen_rounded,
                onTap: () => setState(() => _isFullscreen = !_isFullscreen),
              ),
              const SizedBox(width: 8),
              _OverlayIconBtn(
                icon: _isMuted
                    ? Icons.volume_off_rounded
                    : Icons.volume_up_rounded,
                onTap: () => setState(() => _isMuted = !_isMuted),
              ),
            ],
          ),
        ),

        // ── Overlay bottom: seller info ──────────────────────────
        Positioned(
          bottom: 8,
          left: 12,
          child: Row(
            children: [
              Container(
                width: 28,
                height: 28,
                decoration: BoxDecoration(
                  color: AppColors.gold.withOpacity(0.2),
                  shape: BoxShape.circle,
                  border: Border.all(
                      color: AppColors.gold.withOpacity(0.4), width: 1),
                ),
                child: const Center(
                  child: Text(
                    'م',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppColors.gold,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              const Text(
                'Seller',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: Colors.white70,
                ),
              ),
              const SizedBox(width: 6),
              // ATS score pill
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: AppColors.emerald.withOpacity(0.2),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: const Text(
                  'ATS 92',
                  style: TextStyle(
                    fontFamily: 'Sora',
                    fontSize: 8,
                    fontWeight: FontWeight.w700,
                    color: AppColors.emerald,
                  ),
                ),
              ),
            ],
          ),
        ),

        // ── Back button ──────────────────────────────────────────
        Positioned(
          top: MediaQuery.of(context).padding.top + 4,
          left: 0,
          child: IconButton(
            icon:
                const Icon(Icons.arrow_back_rounded, color: Colors.white70),
            onPressed: () => Navigator.of(context).pop(),
          ),
        ),
      ],
    );
  }

  // ── Tab row ─────────────────────────────────────────────────────

  Widget _buildTabRow() {
    return Container(
      height: 40,
      decoration: BoxDecoration(
        border:
            Border(bottom: BorderSide(color: Colors.white.withOpacity(0.08))),
      ),
      child: Row(
        children: [
          _TabButton(
            label: S.of(context).bids,
            isActive: _tabIndex == 0,
            onTap: () => setState(() => _tabIndex = 0),
          ),
          _TabButton(
            label: S.of(context).chat,
            isActive: _tabIndex == 1,
            onTap: () => setState(() => _tabIndex = 1),
          ),
        ],
      ),
    );
  }

  // ── Compact bid input ───────────────────────────────────────────

  Widget _buildBidInput(AuctionState auction) {
    final minBid = auction.currentPrice + auction.minIncrement;

    return Container(
      padding: EdgeInsets.fromLTRB(
          12, 8, 12, MediaQuery.of(context).padding.bottom + 8),
      decoration: BoxDecoration(
        color: const Color(0xFF1A3050),
        border:
            Border(top: BorderSide(color: Colors.white.withOpacity(0.06))),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Quick chips
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [100.0, 250.0, 500.0].map((amt) {
              return Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: _LiveQuickChip(
                  amount: amt,
                  onTap: () => setState(() => _bidAmount += amt),
                ),
              );
            }).toList(),
          ),
          const SizedBox(height: 8),

          // Input row
          Row(
            children: [
              // Minus
              _CompactStepper(
                icon: Icons.remove,
                enabled: _bidAmount > minBid,
                onTap: () {
                  if (_bidAmount > minBid) {
                    setState(
                        () => _bidAmount -= auction.minIncrement);
                  }
                },
              ),
              const SizedBox(width: 8),

              // Amount display
              Expanded(
                child: Container(
                  height: 36,
                  decoration: BoxDecoration(
                    border: Border.all(
                        color: Colors.white.withOpacity(0.15)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  alignment: Alignment.center,
                  child: Text(
                    ArabicNumerals.formatCurrencyEn(
                        _bidAmount, auction.currency),
                    style: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 15,
                      fontWeight: FontWeight.w800,
                      color: Colors.white,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),

              // Plus
              _CompactStepper(
                icon: Icons.add,
                enabled: true,
                onTap: () =>
                    setState(() => _bidAmount += auction.minIncrement),
              ),
              const SizedBox(width: 10),

              // Place bid button (gold for premium)
              SizedBox(
                height: 48,
                child: ElevatedButton(
                  onPressed: () => _placeBid(auction),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: AppColors.gold,
                    foregroundColor: Colors.white,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    elevation: 0,
                    textStyle: const TextStyle(
                      fontFamily: 'Sora',
                      fontSize: 12,
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                  child: Text(S.of(context).placeBid),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _placeBid(AuctionState auction) {
    final minBid = auction.currentPrice + auction.minIncrement;
    if (_bidAmount < minBid) {
      HapticFeedback.lightImpact();
      return;
    }
    AppHaptics.bidTap();
    ref.read(auctionProvider(widget.auctionId).notifier).placeBid(_bidAmount);
    setState(
        () => _bidAmount = _bidAmount + auction.minIncrement);
  }

  void _sendChat() {
    final text = _chatController.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _chatMessages.insert(
        0,
        _ChatMessage(
          sender: 'You',
          text: text,
          time: DateTime.now(),
        ),
      );
      _chatController.clear();
      _showEmoji = false;
    });
  }
}

// ═══════════════════════════════════════════════════════════════════
// No video placeholder
// ═══════════════════════════════════════════════════════════════════

class _NoVideoPlaceholder extends StatefulWidget {
  @override
  State<_NoVideoPlaceholder> createState() => _NoVideoPlaceholderState();
}

class _NoVideoPlaceholderState extends State<_NoVideoPlaceholder>
    with SingleTickerProviderStateMixin {
  late final AnimationController _dot;
  late final Animation<double> _dotOpacity;

  @override
  void initState() {
    super.initState();
    _dot = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    );
    _dotOpacity = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 0.3, end: 1.0), weight: 50),
      TweenSequenceItem(tween: Tween(begin: 1.0, end: 0.3), weight: 50),
    ]).animate(_dot);
    _dot.repeat();
  }

  @override
  void dispose() {
    _dot.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFF0D0D1A),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            AnimatedBuilder(
              animation: _dotOpacity,
              builder: (_, __) => Container(
                width: 12,
                height: 12,
                decoration: BoxDecoration(
                  color: AppColors.gold.withOpacity(_dotOpacity.value),
                  shape: BoxShape.circle,
                ),
              ),
            ),
            const SizedBox(height: 12),
            const Text(
              'Host is preparing...',
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: Colors.white38,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Auction info strip
// ═══════════════════════════════════════════════════════════════════

class _AuctionInfoStrip extends StatefulWidget {
  const _AuctionInfoStrip({required this.auction});
  final AuctionState auction;

  @override
  State<_AuctionInfoStrip> createState() => _AuctionInfoStripState();
}

class _AuctionInfoStripState extends State<_AuctionInfoStrip>
    with SingleTickerProviderStateMixin {
  Timer? _timer;
  Duration _remaining = Duration.zero;

  late final AnimationController _timerPulse;
  late final Animation<double> _timerPulseScale;

  @override
  void initState() {
    super.initState();
    _timerPulse = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1000),
    );
    _timerPulseScale = TweenSequence<double>([
      TweenSequenceItem(tween: Tween(begin: 1.0, end: 1.06), weight: 50),
      TweenSequenceItem(tween: Tween(begin: 1.06, end: 1.0), weight: 50),
    ]).animate(_timerPulse);

    _startCountdown();
  }

  @override
  void didUpdateWidget(_AuctionInfoStrip old) {
    super.didUpdateWidget(old);
    if (old.auction.endsAt != widget.auction.endsAt) {
      _startCountdown();
    }
  }

  void _startCountdown() {
    _timer?.cancel();
    _updateRemaining();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      _updateRemaining();
    });
  }

  void _updateRemaining() {
    final end = DateTime.tryParse(widget.auction.endsAt ?? '');
    if (end == null) return;
    final diff = end.difference(DateTime.now().toUtc());
    if (!mounted) return;
    setState(() => _remaining = diff.isNegative ? Duration.zero : diff);

    if (_remaining.inSeconds <= 60 && !_timerPulse.isAnimating) {
      _timerPulse.repeat();
    } else if (_remaining.inSeconds > 60 && _timerPulse.isAnimating) {
      _timerPulse.stop();
      _timerPulse.reset();
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    _timerPulse.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final a = widget.auction;
    final h = _remaining.inHours;
    final m = _remaining.inMinutes.remainder(60);
    final s = _remaining.inSeconds.remainder(60);
    final timerText = h > 0
        ? '${_p(h)}:${_p(m)}:${_p(s)}'
        : '${_p(m)}:${_p(s)}';

    return Container(
      height: 40,
      color: AppColors.navy,
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(
        children: [
          // Title + category
          Expanded(
            child: Text(
              a.listingTitle ?? 'Auction',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w500,
                color: Colors.white70,
              ),
            ),
          ),

          // Current price
          Text(
            ArabicNumerals.formatCurrencyEn(a.currentPrice, a.currency),
            style: const TextStyle(
              fontFamily: 'Sora',
              fontSize: 16,
              fontWeight: FontWeight.w800,
              color: AppColors.gold,
            ),
          ),
          const SizedBox(width: 12),

          // Timer
          AnimatedBuilder(
            animation: _timerPulseScale,
            builder: (_, child) {
              final scale = _timerPulse.isAnimating
                  ? _timerPulseScale.value
                  : 1.0;
              return Transform.scale(scale: scale, child: child);
            },
            child: Text(
              timerText,
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: _remaining.inSeconds <= 60
                    ? AppColors.ember
                    : Colors.white54,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _p(int n) => n.toString().padLeft(2, '0');
}

// ═══════════════════════════════════════════════════════════════════
// Bids feed (animated list)
// ═══════════════════════════════════════════════════════════════════

class _BidsFeed extends StatelessWidget {
  const _BidsFeed({required this.bids});
  final List<BidEntry> bids;

  @override
  Widget build(BuildContext context) {
    if (bids.isEmpty) {
      return const Center(
        child: Text(
          'No bids yet',
          style: TextStyle(fontSize: 12, color: Colors.white24),
        ),
      );
    }

    return ListView.builder(
      reverse: false,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      itemCount: bids.length,
      itemBuilder: (_, i) {
        final bid = bids[i];
        return _BidRow(bid: bid, isNew: i == 0);
      },
    );
  }
}

class _BidRow extends StatefulWidget {
  const _BidRow({required this.bid, required this.isNew});
  final BidEntry bid;
  final bool isNew;

  @override
  State<_BidRow> createState() => _BidRowState();
}

class _BidRowState extends State<_BidRow>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 200),
    );
    if (widget.isNew) {
      _ctrl.forward();
    } else {
      _ctrl.value = 1.0;
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bid = widget.bid;
    final maskedName = _maskName(bid.userId);
    final timeAgo = _timeAgo(bid.timestamp);

    return FadeTransition(
      opacity: _ctrl,
      child: SlideTransition(
        position: Tween<Offset>(
          begin: const Offset(0, -0.3),
          end: Offset.zero,
        ).animate(
            CurvedAnimation(parent: _ctrl, curve: Curves.easeOutCubic)),
        child: Container(
          margin: const EdgeInsets.only(bottom: 4),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: BoxDecoration(
            color: bid.isOwn
                ? AppColors.cream.withOpacity(0.06)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
            border: bid.isOwn
                ? Border(
                    left: BorderSide(color: AppColors.emerald, width: 2))
                : null,
          ),
          child: Row(
            children: [
              Expanded(
                child: Row(
                  children: [
                    Text(
                      maskedName,
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: Colors.white70,
                      ),
                    ),
                    if (bid.isOwn) ...[
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 5, vertical: 1),
                        decoration: BoxDecoration(
                          color: AppColors.emerald.withOpacity(0.2),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: const Text(
                          'You',
                          style: TextStyle(
                            fontSize: 8,
                            fontWeight: FontWeight.w700,
                            color: AppColors.emerald,
                          ),
                        ),
                      ),
                    ],
                    if (bid.isPending) ...[
                      const SizedBox(width: 4),
                      SizedBox(
                        width: 10,
                        height: 10,
                        child: CircularProgressIndicator(
                          strokeWidth: 1.5,
                          color: Colors.white30,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              Text(
                ArabicNumerals.formatCurrencyEn(bid.amount, 'JOD'),
                style: const TextStyle(
                  fontFamily: 'Sora',
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: AppColors.gold,
                ),
              ),
              const SizedBox(width: 8),
              Text(
                timeAgo,
                style: const TextStyle(
                  fontSize: 9,
                  color: Colors.white24,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _maskName(String id) {
    if (id.length <= 3) return 'م***';
    return '${id.substring(0, 1)}***${id.substring(id.length - 3)}';
  }

  String _timeAgo(DateTime t) {
    final diff = DateTime.now().difference(t);
    if (diff.inSeconds < 60) return '${diff.inSeconds}s';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m';
    return '${diff.inHours}h';
  }
}

// ═══════════════════════════════════════════════════════════════════
// Chat feed + input
// ═══════════════════════════════════════════════════════════════════

class _ChatMessage {
  const _ChatMessage({
    required this.sender,
    required this.text,
    required this.time,
  });
  final String sender;
  final String text;
  final DateTime time;
}

class _ChatFeed extends StatelessWidget {
  const _ChatFeed({
    required this.messages,
    required this.controller,
    required this.showEmoji,
    required this.onSend,
    required this.onToggleEmoji,
  });

  final List<_ChatMessage> messages;
  final TextEditingController controller;
  final bool showEmoji;
  final VoidCallback onSend;
  final VoidCallback onToggleEmoji;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        // Messages
        Expanded(
          child: messages.isEmpty
              ? const Center(
                  child: Text(
                    'No messages yet',
                    style: TextStyle(fontSize: 12, color: Colors.white24),
                  ),
                )
              : ListView.builder(
                  reverse: true,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                  itemCount: messages.length,
                  itemBuilder: (_, i) {
                    final msg = messages[i];
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${msg.time.hour}:${msg.time.minute.toString().padLeft(2, '0')} ',
                            style: const TextStyle(
                              fontSize: 9,
                              color: Colors.white24,
                            ),
                          ),
                          Expanded(
                            child: Text.rich(
                              TextSpan(
                                children: [
                                  TextSpan(
                                    text: '${msg.sender}  ',
                                    style: const TextStyle(
                                      fontSize: 11,
                                      fontWeight: FontWeight.w700,
                                      color: AppColors.gold,
                                    ),
                                  ),
                                  TextSpan(
                                    text: msg.text,
                                    style: const TextStyle(
                                      fontSize: 11,
                                      color: Colors.white70,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ],
                      ),
                    );
                  },
                ),
        ),

        // Input
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            border: Border(
                top: BorderSide(color: Colors.white.withOpacity(0.06))),
          ),
          child: Row(
            children: [
              GestureDetector(
                onTap: onToggleEmoji,
                child: const Icon(Icons.emoji_emotions_rounded,
                    color: Colors.white30, size: 22),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: TextField(
                  controller: controller,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Colors.white,
                  ),
                  decoration: InputDecoration(
                    hintText: S.of(context).chatHint,
                    hintStyle: const TextStyle(fontSize: 12, color: Colors.white24),
                    border: InputBorder.none,
                    isDense: true,
                    contentPadding: const EdgeInsets.symmetric(vertical: 8),
                  ),
                  onSubmitted: (_) => onSend(),
                ),
              ),
              GestureDetector(
                onTap: onSend,
                child: const Icon(Icons.send_rounded,
                    color: AppColors.gold, size: 20),
              ),
            ],
          ),
        ),

        // Emoji grid
        AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          height: showEmoji ? 120 : 0,
          child: showEmoji
              ? GridView.count(
                  crossAxisCount: 8,
                  padding: const EdgeInsets.all(8),
                  children: '😍🔥👏💰🤩🎉👀💎🏆✨🙌🫡😎🥇💪🎯'
                      .characters
                      .map((e) => GestureDetector(
                            onTap: () {
                              controller.text += e;
                              controller.selection = TextSelection.collapsed(
                                  offset: controller.text.length);
                            },
                            child: Center(
                              child: Text(e,
                                  style: const TextStyle(fontSize: 22)),
                            ),
                          ))
                      .toList(),
                )
              : const SizedBox.shrink(),
        ),
      ],
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Shared small widgets
// ═══════════════════════════════════════════════════════════════════

class _OverlayIconBtn extends StatelessWidget {
  const _OverlayIconBtn({required this.icon, required this.onTap});
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 32,
        height: 32,
        decoration: BoxDecoration(
          color: Colors.black38,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Icon(icon, color: Colors.white70, size: 18),
      ),
    );
  }
}

class _TabButton extends StatelessWidget {
  const _TabButton({
    required this.label,
    required this.isActive,
    required this.onTap,
  });
  final String label;
  final bool isActive;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              label,
              style: TextStyle(
                fontFamily: 'Sora',
                fontSize: 12,
                fontWeight: FontWeight.w700,
                color: isActive ? Colors.white : Colors.white38,
              ),
            ),
            const SizedBox(height: 4),
            AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              height: 2,
              width: isActive ? 24 : 0,
              decoration: BoxDecoration(
                color: AppColors.gold,
                borderRadius: BorderRadius.circular(1),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CompactStepper extends StatelessWidget {
  const _CompactStepper({
    required this.icon,
    required this.enabled,
    required this.onTap,
  });
  final IconData icon;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: enabled ? onTap : null,
      child: AnimatedOpacity(
        duration: const Duration(milliseconds: 150),
        opacity: enabled ? 1.0 : 0.3,
        child: Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: Colors.white.withOpacity(0.15)),
          ),
          child: Icon(icon, color: Colors.white70, size: 18),
        ),
      ),
    );
  }
}

class _LiveQuickChip extends StatefulWidget {
  const _LiveQuickChip({required this.amount, required this.onTap});
  final double amount;
  final VoidCallback onTap;

  @override
  State<_LiveQuickChip> createState() => _LiveQuickChipState();
}

class _LiveQuickChipState extends State<_LiveQuickChip>
    with SingleTickerProviderStateMixin {
  late final AnimationController _scale;

  @override
  void initState() {
    super.initState();
    _scale = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 80),
      reverseDuration: const Duration(milliseconds: 150),
      lowerBound: 1.0,
      upperBound: 1.12,
    );
  }

  @override
  void dispose() {
    _scale.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _scale,
      builder: (_, child) =>
          Transform.scale(scale: _scale.value, child: child),
      child: GestureDetector(
        onTap: () {
          _scale.forward().then((_) => _scale.reverse());
          HapticFeedback.selectionClick();
          widget.onTap();
        },
        child: Container(
          height: 28,
          padding: const EdgeInsets.symmetric(horizontal: 12),
          decoration: BoxDecoration(
            color: AppColors.gold.withOpacity(0.12),
            borderRadius: BorderRadius.circular(6),
          ),
          alignment: Alignment.center,
          child: Text(
            '+${widget.amount.toInt()}',
            style: const TextStyle(
              fontFamily: 'Sora',
              fontSize: 10,
              fontWeight: FontWeight.w700,
              color: AppColors.gold,
            ),
          ),
        ),
      ),
    );
  }
}

// ═══════════════════════════════════════════════════════════════════
// Connection status banner
// ═══════════════════════════════════════════════════════════════════

class _ConnectionBanner extends StatelessWidget {
  const _ConnectionBanner({required this.status});
  final ConnectionStatus status;

  @override
  Widget build(BuildContext context) {
    if (status == ConnectionStatus.connected) {
      return const SizedBox.shrink();
    }

    final isReconnecting = status == ConnectionStatus.reconnecting;
    return SafeArea(
      bottom: false,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        color: isReconnecting
            ? const Color(0xFFF59E0B).withOpacity(0.9) // amber
            : AppColors.ember.withOpacity(0.9),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            if (isReconnecting)
              const SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(
                  strokeWidth: 1.5,
                  color: Colors.white,
                ),
              ),
            if (isReconnecting) const SizedBox(width: 8),
            Text(
              isReconnecting
                  ? 'Connection lost — reconnecting...'
                  : 'Disconnected',
              style: const TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.w600,
                color: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
