// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class SEn extends S {
  SEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'MZADAK';

  @override
  String get navHome => 'Home';

  @override
  String get navBrowse => 'Browse';

  @override
  String get navSell => 'Sell';

  @override
  String get navSaved => 'Saved';

  @override
  String get navProfile => 'Profile';

  @override
  String get view => 'View';

  @override
  String get cancel => 'Cancel';

  @override
  String get confirm => 'Confirm';

  @override
  String get ok => 'OK';

  @override
  String get save => 'Save';

  @override
  String get delete => 'Delete';

  @override
  String get edit => 'Edit';

  @override
  String get undo => 'Undo';

  @override
  String get retry => 'Retry';

  @override
  String get close => 'Close';

  @override
  String get next => 'Next';

  @override
  String get previous => 'Previous';

  @override
  String get submit => 'Submit';

  @override
  String get done => 'Done';

  @override
  String get loading => 'Loading...';

  @override
  String get search => 'Search';

  @override
  String get share => 'Share';

  @override
  String get camera => 'Camera';

  @override
  String get gallery => 'Gallery';

  @override
  String get add => 'Add';

  @override
  String get categoryAll => 'All';

  @override
  String get categoryElectronics => 'Electronics';

  @override
  String get categoryVehicles => 'Vehicles';

  @override
  String get categoryRealEstate => 'Real Estate';

  @override
  String get categoryJewelry => 'Jewelry';

  @override
  String get categoryWatches => 'Watches';

  @override
  String get categoryFashion => 'Fashion';

  @override
  String get categoryArt => 'Art & Antiques';

  @override
  String get categoryFurniture => 'Furniture';

  @override
  String get categorySports => 'Sports';

  @override
  String get categoryBooks => 'Books';

  @override
  String get categoryOther => 'Other';

  @override
  String get conditionBrandNew => 'Brand New';

  @override
  String get conditionLikeNew => 'Like New';

  @override
  String get conditionGood => 'Good';

  @override
  String get conditionFair => 'Fair';

  @override
  String get conditionAcceptable => 'Acceptable';

  @override
  String get searchHint => 'Search auctions...';

  @override
  String get searchHintWatches => 'Luxury watches...';

  @override
  String get searchHintCars => 'Cars...';

  @override
  String get searchHintElectronics => 'Electronics...';

  @override
  String get searchHintJewelry => 'Jewelry...';

  @override
  String get sortEndingSoon => 'Ending soon';

  @override
  String get sortLowestPrice => 'Lowest price';

  @override
  String get sortMostBids => 'Most bids';

  @override
  String get sortNewest => 'Newest';

  @override
  String bidCount(String count) {
    return '$count bids';
  }

  @override
  String get liveBadge => 'LIVE';

  @override
  String get certifiedBadge => 'CERTIFIED';

  @override
  String get buyNowBadge => 'Buy Now';

  @override
  String get charityBadge => 'Charity';

  @override
  String get primaryBadge => 'Primary';

  @override
  String get categoryLabel => 'Category';

  @override
  String get conditionLabel => 'Condition';

  @override
  String get locationLabel => 'Location';

  @override
  String get minBidLabel => 'Minimum bid';

  @override
  String get viewsLabel => 'Views';

  @override
  String get publishedDateLabel => 'Published';

  @override
  String get followersLabel => 'Followers';

  @override
  String get bidHistory => 'Bid History';

  @override
  String get bidTab => 'Bids';

  @override
  String get viewersTab => 'Viewers';

  @override
  String get extensionTab => 'Extend';

  @override
  String get placeBid => 'Place bid';

  @override
  String get placeYourBid => 'Place your bid';

  @override
  String get proxyBid => 'Proxy bid';

  @override
  String minimumBid(String amount) {
    return 'Minimum $amount';
  }

  @override
  String get proxyMaxLowerThanBid => 'Your proxy max is lower than your bid';

  @override
  String get submitBid => 'Submit Bid';

  @override
  String get bidSubmitted => 'Bid submitted successfully';

  @override
  String get paymentStep => 'Payment';

  @override
  String get shippingStep => 'Shipping';

  @override
  String get inTransitStep => 'In Transit';

  @override
  String get deliveryStep => 'Delivery';

  @override
  String get releaseStep => 'Release';

  @override
  String get payNow => 'Pay Now';

  @override
  String get createAramexLabel => 'Create Aramex Label';

  @override
  String get enterTrackingNumber => 'Enter Tracking Number';

  @override
  String get trackShipment => 'Track Shipment';

  @override
  String get confirmReceipt => 'Confirm Receipt';

  @override
  String get reportIssue => 'Report Issue';

  @override
  String get trackingNumberLabel => 'Tracking number';

  @override
  String get trackingNumberHint => 'e.g. 1234567890';

  @override
  String get shippingLabelCreated => 'Shipping label created successfully';

  @override
  String get confirmReceiptTitle => 'Confirm Receipt';

  @override
  String get confirmReceiptBody =>
      'Are you sure you received the item in good condition? The funds will be released to the seller.';

  @override
  String get disputeImageTooLarge => 'Photo exceeds 5MB limit';

  @override
  String get disputeMaxPhotos => 'Maximum 10 photos allowed';

  @override
  String get disputeNotAsDescribed => 'Not as described';

  @override
  String get disputeNotAsDescribedSub =>
      'Item differs from photos or description';

  @override
  String get disputeNotReceived => 'Not received';

  @override
  String get disputeNotReceivedSub => 'I did not receive the item';

  @override
  String get disputeDamaged => 'Damaged';

  @override
  String get disputeDamagedSub => 'Item arrived damaged or broken';

  @override
  String get disputeCounterfeit => 'Counterfeit';

  @override
  String get disputeCounterfeitSub => 'Item is not authentic';

  @override
  String get disputeWrongItem => 'Wrong item';

  @override
  String get disputeWrongItemSub => 'Received a different item';

  @override
  String get disputeOther => 'Other';

  @override
  String get disputeOtherSub => 'Other reason';

  @override
  String get disputeExplain => 'Explain what happened...';

  @override
  String disputeSubmitFailed(String error) {
    return 'Failed to submit: $error';
  }

  @override
  String get photoAnalysis => 'Photo Analysis';

  @override
  String get productClassification => 'Product Classification';

  @override
  String get brandConditionDetection => 'Brand & Condition Detection';

  @override
  String get generateListing => 'Generate Listing';

  @override
  String get gpt4oArabicEnglish => 'GPT-4o Arabic/English';

  @override
  String get priceEstimation => 'Price Estimation';

  @override
  String get aiPriceEstimation => 'AI Price Estimation';

  @override
  String get permissionRequired => 'Permission Required';

  @override
  String publishFailed(String error) {
    return 'Publish failed: $error';
  }

  @override
  String get addMinPhotos => 'Add at least 3 photos';

  @override
  String get photosStep => 'Photos';

  @override
  String get detailsStep => 'Details';

  @override
  String get pricingStep => 'Pricing';

  @override
  String get scheduleStep => 'Schedule';

  @override
  String get reviewStep => 'Review';

  @override
  String get startNow => 'Start now';

  @override
  String get titleAr => 'Title (Arabic)';

  @override
  String get titleEn => 'Title (English)';

  @override
  String get descriptionAr => 'Description (Arabic)';

  @override
  String get descriptionEn => 'Description (English)';

  @override
  String get startingPrice => 'Starting price';

  @override
  String get reservePrice => 'Reserve price';

  @override
  String get buyNowPrice => 'Buy Now price';

  @override
  String get minIncrement => 'Minimum increment';

  @override
  String get startTime => 'Start time';

  @override
  String get endTime => 'End time';

  @override
  String get publish => 'Publish';

  @override
  String get publishListing => 'Publish Listing';

  @override
  String get useAi => 'Use AI';

  @override
  String get snapToList => 'Snap to List';

  @override
  String get identityVerification => 'Identity Verification';

  @override
  String get profileCompletion => 'Profile Completion';

  @override
  String get shippingSpeed => 'Shipping Speed';

  @override
  String get buyerRatings => 'Buyer Ratings';

  @override
  String get listingQuality => 'Listing Quality';

  @override
  String get disputes => 'Disputes';

  @override
  String get salesLabel => 'Sales';

  @override
  String get ratingLabel => 'Rating';

  @override
  String get commissionLabel => 'Commission';

  @override
  String get rankingLabel => 'Ranking';

  @override
  String get levelLabel => 'Level';

  @override
  String get authGetStarted => 'Get started';

  @override
  String get authContinue => 'Continue';

  @override
  String get authCodeResent => 'Code resent';

  @override
  String get authGoHome => 'Go to Home';

  @override
  String get authTooManyAttempts =>
      'Too many attempts. Please wait and try again';

  @override
  String get authConnectionError => 'Connection error. Please try again';

  @override
  String get authGenericError => 'Something went wrong. Please try again';

  @override
  String get authEnterPhone => 'Enter phone number';

  @override
  String get authEnterOtp => 'Enter verification code';

  @override
  String get authSearchCountry => 'Search country...';

  @override
  String get authTakeSelfie => 'Take selfie';

  @override
  String get authRetakeSelfie => 'Retake selfie';

  @override
  String get authTakePhoto => 'Take photo';

  @override
  String get authUpload => 'Upload';

  @override
  String get authSubmitVerification => 'Submit for verification';

  @override
  String get smartEscrow => 'Smart Escrow';

  @override
  String get aiPricing => 'AI Pricing';

  @override
  String get whatsappBids => 'WhatsApp Bids';

  @override
  String get settingsEditProfile => 'Edit profile';

  @override
  String get settingsPhone => 'Phone number';

  @override
  String get settingsEmail => 'Email address';

  @override
  String get settingsNotifications => 'Notification preferences';

  @override
  String get settingsMyListings => 'My listings';

  @override
  String get settingsPayoutBank => 'Payout bank account';

  @override
  String get settingsSellerAnalytics => 'Seller analytics';

  @override
  String get settingsBiometric => 'Biometric login';

  @override
  String get settingsActiveSessions => 'Active sessions';

  @override
  String get settingsDeleteAccount => 'Delete account';

  @override
  String get settingsHelpCenter => 'Help center';

  @override
  String get settingsReportBug => 'Report a bug';

  @override
  String get settingsPrivacyPolicy => 'Privacy policy';

  @override
  String get settingsTerms => 'Terms of service';

  @override
  String get settingsDarkModeSoon => 'Coming soon — Dark mode in v2';

  @override
  String get settingsLogoutTitle => 'Log out of MZADAK?';

  @override
  String get settingsLogout => 'Log out';

  @override
  String get settingsDeleteConfirmTitle => 'Type DELETE to confirm';

  @override
  String get settingsDeleteConfirmHint => 'DELETE';

  @override
  String get settingsAccountDeleted => 'Account deletion requested';

  @override
  String get settingsDebugInfo => 'Debug Info';

  @override
  String get noActiveListings => 'No active listings';

  @override
  String get noEndedListings => 'No ended listings';

  @override
  String get noDrafts => 'No drafts';

  @override
  String get noPendingReviews => 'No pending reviews';

  @override
  String get noActiveAuctions => 'No active auctions';

  @override
  String get noEndedAuctions => 'No ended auctions';

  @override
  String get noAuctionsWon => 'No auctions won yet';

  @override
  String get noActiveBids => 'No active bids';

  @override
  String get noWinsYet => 'No wins yet';

  @override
  String get noLostBids => 'No lost bids';

  @override
  String get watchlistEmpty => 'Watchlist empty';

  @override
  String get removedFromWatchlist => 'Removed from watchlist';

  @override
  String get cannotEditWithBids => 'Cannot edit listing with active bids';

  @override
  String get endListingEarly => 'End listing early?';

  @override
  String get endNow => 'End now';

  @override
  String get editListing => 'Edit listing';

  @override
  String get endEarly => 'End early';

  @override
  String get viewAnalytics => 'View analytics';

  @override
  String get linkCopied => 'Link copied';

  @override
  String get markAsRead => 'Mark as read';

  @override
  String get notificationsTitle => 'Notifications';

  @override
  String get bids => 'Bids';

  @override
  String get chat => 'Chat';

  @override
  String get chatHint => 'Say something...';

  @override
  String get noCommission => '0% commission';

  @override
  String get zakat => 'Zakat';

  @override
  String get customAmountHint => 'Custom amount';

  @override
  String priceFrom(String price) {
    return 'From $price JOD';
  }

  @override
  String priceTo(String price) {
    return 'Up to $price JOD';
  }

  @override
  String get priceMin => 'Minimum';

  @override
  String get priceMax => 'Maximum';

  @override
  String get clearAll => 'Clear all';

  @override
  String get applyFilters => 'Apply Filters';

  @override
  String get enterBidAmount => 'Please enter a bid amount';

  @override
  String get invalidAmount => 'Invalid amount';

  @override
  String get days30 => '30 days';

  @override
  String get days60 => '60 days';

  @override
  String get days90 => '90 days';

  @override
  String get technicalProposalHint => 'Enter technical proposal or notes...';

  @override
  String get duration1h => '1h';

  @override
  String get duration3h => '3h';

  @override
  String get duration6h => '6h';

  @override
  String get duration12h => '12h';

  @override
  String get duration24h => '24h';

  @override
  String get duration3d => '3d';

  @override
  String get duration7d => '7d';

  @override
  String get jod => 'JOD';

  @override
  String get currency => 'JOD';
}
