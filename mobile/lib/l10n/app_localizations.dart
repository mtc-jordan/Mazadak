import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of S
/// returned by `S.of(context)`.
///
/// Applications need to include `S.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'l10n/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: S.localizationsDelegates,
///   supportedLocales: S.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the S.supportedLocales
/// property.
abstract class S {
  S(String locale)
      : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static S of(BuildContext context) {
    return Localizations.of<S>(context, S)!;
  }

  static const LocalizationsDelegate<S> delegate = _SDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en')
  ];

  /// No description provided for @appTitle.
  ///
  /// In ar, this message translates to:
  /// **'مزادك'**
  String get appTitle;

  /// No description provided for @navHome.
  ///
  /// In ar, this message translates to:
  /// **'الرئيسية'**
  String get navHome;

  /// No description provided for @navBrowse.
  ///
  /// In ar, this message translates to:
  /// **'تصفح'**
  String get navBrowse;

  /// No description provided for @navSell.
  ///
  /// In ar, this message translates to:
  /// **'بيع'**
  String get navSell;

  /// No description provided for @navSaved.
  ///
  /// In ar, this message translates to:
  /// **'المحفوظات'**
  String get navSaved;

  /// No description provided for @navProfile.
  ///
  /// In ar, this message translates to:
  /// **'حسابي'**
  String get navProfile;

  /// No description provided for @view.
  ///
  /// In ar, this message translates to:
  /// **'عرض'**
  String get view;

  /// No description provided for @cancel.
  ///
  /// In ar, this message translates to:
  /// **'إلغاء'**
  String get cancel;

  /// No description provided for @confirm.
  ///
  /// In ar, this message translates to:
  /// **'تأكيد'**
  String get confirm;

  /// No description provided for @ok.
  ///
  /// In ar, this message translates to:
  /// **'حسنًا'**
  String get ok;

  /// No description provided for @save.
  ///
  /// In ar, this message translates to:
  /// **'حفظ'**
  String get save;

  /// No description provided for @delete.
  ///
  /// In ar, this message translates to:
  /// **'حذف'**
  String get delete;

  /// No description provided for @edit.
  ///
  /// In ar, this message translates to:
  /// **'تعديل'**
  String get edit;

  /// No description provided for @undo.
  ///
  /// In ar, this message translates to:
  /// **'تراجع'**
  String get undo;

  /// No description provided for @retry.
  ///
  /// In ar, this message translates to:
  /// **'إعادة المحاولة'**
  String get retry;

  /// No description provided for @close.
  ///
  /// In ar, this message translates to:
  /// **'إغلاق'**
  String get close;

  /// No description provided for @next.
  ///
  /// In ar, this message translates to:
  /// **'التالي'**
  String get next;

  /// No description provided for @previous.
  ///
  /// In ar, this message translates to:
  /// **'السابق'**
  String get previous;

  /// No description provided for @submit.
  ///
  /// In ar, this message translates to:
  /// **'إرسال'**
  String get submit;

  /// No description provided for @done.
  ///
  /// In ar, this message translates to:
  /// **'تم'**
  String get done;

  /// No description provided for @loading.
  ///
  /// In ar, this message translates to:
  /// **'جاري التحميل...'**
  String get loading;

  /// No description provided for @search.
  ///
  /// In ar, this message translates to:
  /// **'بحث'**
  String get search;

  /// No description provided for @share.
  ///
  /// In ar, this message translates to:
  /// **'مشاركة'**
  String get share;

  /// No description provided for @camera.
  ///
  /// In ar, this message translates to:
  /// **'الكاميرا'**
  String get camera;

  /// No description provided for @gallery.
  ///
  /// In ar, this message translates to:
  /// **'المعرض'**
  String get gallery;

  /// No description provided for @add.
  ///
  /// In ar, this message translates to:
  /// **'إضافة'**
  String get add;

  /// No description provided for @categoryAll.
  ///
  /// In ar, this message translates to:
  /// **'الكل'**
  String get categoryAll;

  /// No description provided for @categoryElectronics.
  ///
  /// In ar, this message translates to:
  /// **'إلكترونيات'**
  String get categoryElectronics;

  /// No description provided for @categoryVehicles.
  ///
  /// In ar, this message translates to:
  /// **'سيارات'**
  String get categoryVehicles;

  /// No description provided for @categoryRealEstate.
  ///
  /// In ar, this message translates to:
  /// **'عقارات'**
  String get categoryRealEstate;

  /// No description provided for @categoryJewelry.
  ///
  /// In ar, this message translates to:
  /// **'مجوهرات'**
  String get categoryJewelry;

  /// No description provided for @categoryWatches.
  ///
  /// In ar, this message translates to:
  /// **'ساعات'**
  String get categoryWatches;

  /// No description provided for @categoryFashion.
  ///
  /// In ar, this message translates to:
  /// **'أزياء'**
  String get categoryFashion;

  /// No description provided for @categoryArt.
  ///
  /// In ar, this message translates to:
  /// **'فن وتحف'**
  String get categoryArt;

  /// No description provided for @categoryFurniture.
  ///
  /// In ar, this message translates to:
  /// **'أثاث'**
  String get categoryFurniture;

  /// No description provided for @categorySports.
  ///
  /// In ar, this message translates to:
  /// **'رياضة'**
  String get categorySports;

  /// No description provided for @categoryBooks.
  ///
  /// In ar, this message translates to:
  /// **'كتب'**
  String get categoryBooks;

  /// No description provided for @categoryOther.
  ///
  /// In ar, this message translates to:
  /// **'أخرى'**
  String get categoryOther;

  /// No description provided for @conditionBrandNew.
  ///
  /// In ar, this message translates to:
  /// **'جديد'**
  String get conditionBrandNew;

  /// No description provided for @conditionLikeNew.
  ///
  /// In ar, this message translates to:
  /// **'شبه جديد'**
  String get conditionLikeNew;

  /// No description provided for @conditionGood.
  ///
  /// In ar, this message translates to:
  /// **'جيد'**
  String get conditionGood;

  /// No description provided for @conditionFair.
  ///
  /// In ar, this message translates to:
  /// **'مقبول'**
  String get conditionFair;

  /// No description provided for @conditionAcceptable.
  ///
  /// In ar, this message translates to:
  /// **'مستعمل'**
  String get conditionAcceptable;

  /// No description provided for @searchHint.
  ///
  /// In ar, this message translates to:
  /// **'ابحث في المزادات...'**
  String get searchHint;

  /// No description provided for @searchHintWatches.
  ///
  /// In ar, this message translates to:
  /// **'ساعات فاخرة...'**
  String get searchHintWatches;

  /// No description provided for @searchHintCars.
  ///
  /// In ar, this message translates to:
  /// **'سيارات...'**
  String get searchHintCars;

  /// No description provided for @searchHintElectronics.
  ///
  /// In ar, this message translates to:
  /// **'إلكترونيات...'**
  String get searchHintElectronics;

  /// No description provided for @searchHintJewelry.
  ///
  /// In ar, this message translates to:
  /// **'مجوهرات...'**
  String get searchHintJewelry;

  /// No description provided for @sortEndingSoon.
  ///
  /// In ar, this message translates to:
  /// **'ينتهي قريباً'**
  String get sortEndingSoon;

  /// No description provided for @sortLowestPrice.
  ///
  /// In ar, this message translates to:
  /// **'الأقل سعراً'**
  String get sortLowestPrice;

  /// No description provided for @sortMostBids.
  ///
  /// In ar, this message translates to:
  /// **'الأكثر مزايدة'**
  String get sortMostBids;

  /// No description provided for @sortNewest.
  ///
  /// In ar, this message translates to:
  /// **'الأحدث'**
  String get sortNewest;

  /// No description provided for @bidCount.
  ///
  /// In ar, this message translates to:
  /// **'{count} مزايدة'**
  String bidCount(String count);

  /// No description provided for @liveBadge.
  ///
  /// In ar, this message translates to:
  /// **'مباشر'**
  String get liveBadge;

  /// No description provided for @certifiedBadge.
  ///
  /// In ar, this message translates to:
  /// **'موثّق'**
  String get certifiedBadge;

  /// No description provided for @buyNowBadge.
  ///
  /// In ar, this message translates to:
  /// **'شراء فوري'**
  String get buyNowBadge;

  /// No description provided for @charityBadge.
  ///
  /// In ar, this message translates to:
  /// **'خيري'**
  String get charityBadge;

  /// No description provided for @primaryBadge.
  ///
  /// In ar, this message translates to:
  /// **'رئيسية'**
  String get primaryBadge;

  /// No description provided for @categoryLabel.
  ///
  /// In ar, this message translates to:
  /// **'الفئة'**
  String get categoryLabel;

  /// No description provided for @conditionLabel.
  ///
  /// In ar, this message translates to:
  /// **'الحالة'**
  String get conditionLabel;

  /// No description provided for @locationLabel.
  ///
  /// In ar, this message translates to:
  /// **'الموقع'**
  String get locationLabel;

  /// No description provided for @minBidLabel.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأدنى للمزايدة'**
  String get minBidLabel;

  /// No description provided for @viewsLabel.
  ///
  /// In ar, this message translates to:
  /// **'المشاهدات'**
  String get viewsLabel;

  /// No description provided for @publishedDateLabel.
  ///
  /// In ar, this message translates to:
  /// **'تاريخ النشر'**
  String get publishedDateLabel;

  /// No description provided for @followersLabel.
  ///
  /// In ar, this message translates to:
  /// **'المتابعون'**
  String get followersLabel;

  /// No description provided for @bidHistory.
  ///
  /// In ar, this message translates to:
  /// **'سجل المزايدات'**
  String get bidHistory;

  /// No description provided for @bidTab.
  ///
  /// In ar, this message translates to:
  /// **'مزايدة'**
  String get bidTab;

  /// No description provided for @viewersTab.
  ///
  /// In ar, this message translates to:
  /// **'مشاهد'**
  String get viewersTab;

  /// No description provided for @extensionTab.
  ///
  /// In ar, this message translates to:
  /// **'تمديد'**
  String get extensionTab;

  /// No description provided for @placeBid.
  ///
  /// In ar, this message translates to:
  /// **'زايد الآن'**
  String get placeBid;

  /// No description provided for @placeYourBid.
  ///
  /// In ar, this message translates to:
  /// **'ضع مزايدتك'**
  String get placeYourBid;

  /// No description provided for @proxyBid.
  ///
  /// In ar, this message translates to:
  /// **'مزايدة وكيل'**
  String get proxyBid;

  /// No description provided for @minimumBid.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأدنى {amount}'**
  String minimumBid(String amount);

  /// No description provided for @proxyMaxLowerThanBid.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأقصى للوكيل أقل من مزايدتك'**
  String get proxyMaxLowerThanBid;

  /// No description provided for @submitBid.
  ///
  /// In ar, this message translates to:
  /// **'تقديم المزايدة'**
  String get submitBid;

  /// No description provided for @bidSubmitted.
  ///
  /// In ar, this message translates to:
  /// **'تم تقديم المزايدة بنجاح'**
  String get bidSubmitted;

  /// No description provided for @paymentStep.
  ///
  /// In ar, this message translates to:
  /// **'الدفع'**
  String get paymentStep;

  /// No description provided for @shippingStep.
  ///
  /// In ar, this message translates to:
  /// **'الشحن'**
  String get shippingStep;

  /// No description provided for @inTransitStep.
  ///
  /// In ar, this message translates to:
  /// **'في الطريق'**
  String get inTransitStep;

  /// No description provided for @deliveryStep.
  ///
  /// In ar, this message translates to:
  /// **'التسليم'**
  String get deliveryStep;

  /// No description provided for @releaseStep.
  ///
  /// In ar, this message translates to:
  /// **'الإفراج'**
  String get releaseStep;

  /// No description provided for @payNow.
  ///
  /// In ar, this message translates to:
  /// **'ادفع الآن'**
  String get payNow;

  /// No description provided for @createAramexLabel.
  ///
  /// In ar, this message translates to:
  /// **'إنشاء بوليصة أرامكس'**
  String get createAramexLabel;

  /// No description provided for @enterTrackingNumber.
  ///
  /// In ar, this message translates to:
  /// **'إدخال رقم التتبع'**
  String get enterTrackingNumber;

  /// No description provided for @trackShipment.
  ///
  /// In ar, this message translates to:
  /// **'تتبع الشحنة'**
  String get trackShipment;

  /// No description provided for @confirmReceipt.
  ///
  /// In ar, this message translates to:
  /// **'تأكيد الاستلام'**
  String get confirmReceipt;

  /// No description provided for @reportIssue.
  ///
  /// In ar, this message translates to:
  /// **'الإبلاغ عن مشكلة'**
  String get reportIssue;

  /// No description provided for @trackingNumberLabel.
  ///
  /// In ar, this message translates to:
  /// **'رقم التتبع'**
  String get trackingNumberLabel;

  /// No description provided for @trackingNumberHint.
  ///
  /// In ar, this message translates to:
  /// **'مثال: 1234567890'**
  String get trackingNumberHint;

  /// No description provided for @shippingLabelCreated.
  ///
  /// In ar, this message translates to:
  /// **'تم إنشاء بوليصة الشحن بنجاح'**
  String get shippingLabelCreated;

  /// No description provided for @confirmReceiptTitle.
  ///
  /// In ar, this message translates to:
  /// **'تأكيد الاستلام'**
  String get confirmReceiptTitle;

  /// No description provided for @confirmReceiptBody.
  ///
  /// In ar, this message translates to:
  /// **'هل أنت متأكد من استلام الطلب بحالة جيدة؟ سيتم تحرير المبلغ للبائع.'**
  String get confirmReceiptBody;

  /// No description provided for @disputeImageTooLarge.
  ///
  /// In ar, this message translates to:
  /// **'حجم الصورة يتجاوز 5 ميغابايت'**
  String get disputeImageTooLarge;

  /// No description provided for @disputeMaxPhotos.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأقصى ١٠ صور'**
  String get disputeMaxPhotos;

  /// No description provided for @disputeNotAsDescribed.
  ///
  /// In ar, this message translates to:
  /// **'لا يطابق الوصف'**
  String get disputeNotAsDescribed;

  /// No description provided for @disputeNotAsDescribedSub.
  ///
  /// In ar, this message translates to:
  /// **'المنتج يختلف عن الصور أو الوصف'**
  String get disputeNotAsDescribedSub;

  /// No description provided for @disputeNotReceived.
  ///
  /// In ar, this message translates to:
  /// **'لم يصل'**
  String get disputeNotReceived;

  /// No description provided for @disputeNotReceivedSub.
  ///
  /// In ar, this message translates to:
  /// **'لم أستلم المنتج'**
  String get disputeNotReceivedSub;

  /// No description provided for @disputeDamaged.
  ///
  /// In ar, this message translates to:
  /// **'تالف'**
  String get disputeDamaged;

  /// No description provided for @disputeDamagedSub.
  ///
  /// In ar, this message translates to:
  /// **'وصل المنتج تالفاً أو مكسوراً'**
  String get disputeDamagedSub;

  /// No description provided for @disputeCounterfeit.
  ///
  /// In ar, this message translates to:
  /// **'مقلّد'**
  String get disputeCounterfeit;

  /// No description provided for @disputeCounterfeitSub.
  ///
  /// In ar, this message translates to:
  /// **'المنتج ليس أصلياً'**
  String get disputeCounterfeitSub;

  /// No description provided for @disputeWrongItem.
  ///
  /// In ar, this message translates to:
  /// **'منتج خاطئ'**
  String get disputeWrongItem;

  /// No description provided for @disputeWrongItemSub.
  ///
  /// In ar, this message translates to:
  /// **'استلمت منتجاً مختلفاً'**
  String get disputeWrongItemSub;

  /// No description provided for @disputeOther.
  ///
  /// In ar, this message translates to:
  /// **'أخرى'**
  String get disputeOther;

  /// No description provided for @disputeOtherSub.
  ///
  /// In ar, this message translates to:
  /// **'سبب آخر'**
  String get disputeOtherSub;

  /// No description provided for @disputeExplain.
  ///
  /// In ar, this message translates to:
  /// **'اشرح ما حدث...'**
  String get disputeExplain;

  /// No description provided for @disputeSubmitFailed.
  ///
  /// In ar, this message translates to:
  /// **'فشل الإرسال: {error}'**
  String disputeSubmitFailed(String error);

  /// No description provided for @photoAnalysis.
  ///
  /// In ar, this message translates to:
  /// **'تحليل الصور'**
  String get photoAnalysis;

  /// No description provided for @productClassification.
  ///
  /// In ar, this message translates to:
  /// **'تصنيف المنتج'**
  String get productClassification;

  /// No description provided for @brandConditionDetection.
  ///
  /// In ar, this message translates to:
  /// **'كشف العلامة التجارية والحالة'**
  String get brandConditionDetection;

  /// No description provided for @generateListing.
  ///
  /// In ar, this message translates to:
  /// **'كتابة القائمة'**
  String get generateListing;

  /// No description provided for @gpt4oArabicEnglish.
  ///
  /// In ar, this message translates to:
  /// **'GPT-4o عربي/إنجليزي'**
  String get gpt4oArabicEnglish;

  /// No description provided for @priceEstimation.
  ///
  /// In ar, this message translates to:
  /// **'تقدير السعر'**
  String get priceEstimation;

  /// No description provided for @aiPriceEstimation.
  ///
  /// In ar, this message translates to:
  /// **'تقدير السعر بالذكاء الاصطناعي'**
  String get aiPriceEstimation;

  /// No description provided for @permissionRequired.
  ///
  /// In ar, this message translates to:
  /// **'إذن مطلوب'**
  String get permissionRequired;

  /// No description provided for @publishFailed.
  ///
  /// In ar, this message translates to:
  /// **'فشل النشر: {error}'**
  String publishFailed(String error);

  /// No description provided for @addMinPhotos.
  ///
  /// In ar, this message translates to:
  /// **'أضف ٣ صور على الأقل'**
  String get addMinPhotos;

  /// No description provided for @photosStep.
  ///
  /// In ar, this message translates to:
  /// **'الصور'**
  String get photosStep;

  /// No description provided for @detailsStep.
  ///
  /// In ar, this message translates to:
  /// **'التفاصيل'**
  String get detailsStep;

  /// No description provided for @pricingStep.
  ///
  /// In ar, this message translates to:
  /// **'الأسعار'**
  String get pricingStep;

  /// No description provided for @scheduleStep.
  ///
  /// In ar, this message translates to:
  /// **'الجدولة'**
  String get scheduleStep;

  /// No description provided for @reviewStep.
  ///
  /// In ar, this message translates to:
  /// **'المراجعة'**
  String get reviewStep;

  /// No description provided for @startNow.
  ///
  /// In ar, this message translates to:
  /// **'ابدأ فوراً'**
  String get startNow;

  /// No description provided for @titleAr.
  ///
  /// In ar, this message translates to:
  /// **'العنوان بالعربية'**
  String get titleAr;

  /// No description provided for @titleEn.
  ///
  /// In ar, this message translates to:
  /// **'العنوان بالإنجليزية'**
  String get titleEn;

  /// No description provided for @descriptionAr.
  ///
  /// In ar, this message translates to:
  /// **'الوصف بالعربية'**
  String get descriptionAr;

  /// No description provided for @descriptionEn.
  ///
  /// In ar, this message translates to:
  /// **'الوصف بالإنجليزية'**
  String get descriptionEn;

  /// No description provided for @startingPrice.
  ///
  /// In ar, this message translates to:
  /// **'سعر البدء'**
  String get startingPrice;

  /// No description provided for @reservePrice.
  ///
  /// In ar, this message translates to:
  /// **'السعر الاحتياطي'**
  String get reservePrice;

  /// No description provided for @buyNowPrice.
  ///
  /// In ar, this message translates to:
  /// **'سعر الشراء الفوري'**
  String get buyNowPrice;

  /// No description provided for @minIncrement.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأدنى للزيادة'**
  String get minIncrement;

  /// No description provided for @startTime.
  ///
  /// In ar, this message translates to:
  /// **'وقت البدء'**
  String get startTime;

  /// No description provided for @endTime.
  ///
  /// In ar, this message translates to:
  /// **'وقت الانتهاء'**
  String get endTime;

  /// No description provided for @publish.
  ///
  /// In ar, this message translates to:
  /// **'نشر'**
  String get publish;

  /// No description provided for @publishListing.
  ///
  /// In ar, this message translates to:
  /// **'نشر القائمة'**
  String get publishListing;

  /// No description provided for @useAi.
  ///
  /// In ar, this message translates to:
  /// **'استخدم الذكاء الاصطناعي'**
  String get useAi;

  /// No description provided for @snapToList.
  ///
  /// In ar, this message translates to:
  /// **'صوّر وأعلن'**
  String get snapToList;

  /// No description provided for @identityVerification.
  ///
  /// In ar, this message translates to:
  /// **'التحقق من الهوية'**
  String get identityVerification;

  /// No description provided for @profileCompletion.
  ///
  /// In ar, this message translates to:
  /// **'اكتمال الملف'**
  String get profileCompletion;

  /// No description provided for @shippingSpeed.
  ///
  /// In ar, this message translates to:
  /// **'سرعة الشحن'**
  String get shippingSpeed;

  /// No description provided for @buyerRatings.
  ///
  /// In ar, this message translates to:
  /// **'تقييمات المشترين'**
  String get buyerRatings;

  /// No description provided for @listingQuality.
  ///
  /// In ar, this message translates to:
  /// **'جودة القوائم'**
  String get listingQuality;

  /// No description provided for @disputes.
  ///
  /// In ar, this message translates to:
  /// **'النزاعات'**
  String get disputes;

  /// No description provided for @salesLabel.
  ///
  /// In ar, this message translates to:
  /// **'المبيعات'**
  String get salesLabel;

  /// No description provided for @ratingLabel.
  ///
  /// In ar, this message translates to:
  /// **'التقييم'**
  String get ratingLabel;

  /// No description provided for @commissionLabel.
  ///
  /// In ar, this message translates to:
  /// **'العمولة'**
  String get commissionLabel;

  /// No description provided for @rankingLabel.
  ///
  /// In ar, this message translates to:
  /// **'الترتيب'**
  String get rankingLabel;

  /// No description provided for @levelLabel.
  ///
  /// In ar, this message translates to:
  /// **'المستوى'**
  String get levelLabel;

  /// No description provided for @authGetStarted.
  ///
  /// In ar, this message translates to:
  /// **'ابدأ الآن'**
  String get authGetStarted;

  /// No description provided for @authContinue.
  ///
  /// In ar, this message translates to:
  /// **'متابعة'**
  String get authContinue;

  /// No description provided for @authCodeResent.
  ///
  /// In ar, this message translates to:
  /// **'تم إعادة إرسال الرمز'**
  String get authCodeResent;

  /// No description provided for @authGoHome.
  ///
  /// In ar, this message translates to:
  /// **'الرئيسية'**
  String get authGoHome;

  /// No description provided for @authTooManyAttempts.
  ///
  /// In ar, this message translates to:
  /// **'محاولات كثيرة. حاول مرة أخرى لاحقاً'**
  String get authTooManyAttempts;

  /// No description provided for @authConnectionError.
  ///
  /// In ar, this message translates to:
  /// **'خطأ في الاتصال، حاول مجدداً'**
  String get authConnectionError;

  /// No description provided for @authGenericError.
  ///
  /// In ar, this message translates to:
  /// **'حدث خطأ، حاول مجدداً'**
  String get authGenericError;

  /// No description provided for @authEnterPhone.
  ///
  /// In ar, this message translates to:
  /// **'أدخل رقم الهاتف'**
  String get authEnterPhone;

  /// No description provided for @authEnterOtp.
  ///
  /// In ar, this message translates to:
  /// **'أدخل رمز التحقق'**
  String get authEnterOtp;

  /// No description provided for @authSearchCountry.
  ///
  /// In ar, this message translates to:
  /// **'بحث عن دولة...'**
  String get authSearchCountry;

  /// No description provided for @authTakeSelfie.
  ///
  /// In ar, this message translates to:
  /// **'التقط صورة شخصية'**
  String get authTakeSelfie;

  /// No description provided for @authRetakeSelfie.
  ///
  /// In ar, this message translates to:
  /// **'أعد التقاط الصورة'**
  String get authRetakeSelfie;

  /// No description provided for @authTakePhoto.
  ///
  /// In ar, this message translates to:
  /// **'التقط صورة'**
  String get authTakePhoto;

  /// No description provided for @authUpload.
  ///
  /// In ar, this message translates to:
  /// **'رفع'**
  String get authUpload;

  /// No description provided for @authSubmitVerification.
  ///
  /// In ar, this message translates to:
  /// **'إرسال للتحقق'**
  String get authSubmitVerification;

  /// No description provided for @smartEscrow.
  ///
  /// In ar, this message translates to:
  /// **'ضمان ذكي'**
  String get smartEscrow;

  /// No description provided for @aiPricing.
  ///
  /// In ar, this message translates to:
  /// **'تسعير ذكي'**
  String get aiPricing;

  /// No description provided for @whatsappBids.
  ///
  /// In ar, this message translates to:
  /// **'مزايدة واتساب'**
  String get whatsappBids;

  /// No description provided for @settingsEditProfile.
  ///
  /// In ar, this message translates to:
  /// **'تعديل الملف الشخصي'**
  String get settingsEditProfile;

  /// No description provided for @settingsPhone.
  ///
  /// In ar, this message translates to:
  /// **'رقم الهاتف'**
  String get settingsPhone;

  /// No description provided for @settingsEmail.
  ///
  /// In ar, this message translates to:
  /// **'البريد الإلكتروني'**
  String get settingsEmail;

  /// No description provided for @settingsNotifications.
  ///
  /// In ar, this message translates to:
  /// **'إعدادات الإشعارات'**
  String get settingsNotifications;

  /// No description provided for @settingsMyListings.
  ///
  /// In ar, this message translates to:
  /// **'قوائمي'**
  String get settingsMyListings;

  /// No description provided for @settingsPayoutBank.
  ///
  /// In ar, this message translates to:
  /// **'حساب البنك للدفع'**
  String get settingsPayoutBank;

  /// No description provided for @settingsSellerAnalytics.
  ///
  /// In ar, this message translates to:
  /// **'إحصائيات البائع'**
  String get settingsSellerAnalytics;

  /// No description provided for @settingsBiometric.
  ///
  /// In ar, this message translates to:
  /// **'تسجيل دخول بيومتري'**
  String get settingsBiometric;

  /// No description provided for @settingsActiveSessions.
  ///
  /// In ar, this message translates to:
  /// **'الجلسات النشطة'**
  String get settingsActiveSessions;

  /// No description provided for @settingsDeleteAccount.
  ///
  /// In ar, this message translates to:
  /// **'حذف الحساب'**
  String get settingsDeleteAccount;

  /// No description provided for @settingsHelpCenter.
  ///
  /// In ar, this message translates to:
  /// **'مركز المساعدة'**
  String get settingsHelpCenter;

  /// No description provided for @settingsReportBug.
  ///
  /// In ar, this message translates to:
  /// **'الإبلاغ عن خطأ'**
  String get settingsReportBug;

  /// No description provided for @settingsPrivacyPolicy.
  ///
  /// In ar, this message translates to:
  /// **'سياسة الخصوصية'**
  String get settingsPrivacyPolicy;

  /// No description provided for @settingsTerms.
  ///
  /// In ar, this message translates to:
  /// **'شروط الخدمة'**
  String get settingsTerms;

  /// No description provided for @settingsDarkModeSoon.
  ///
  /// In ar, this message translates to:
  /// **'الوضع الليلي قريباً في الإصدار الثاني'**
  String get settingsDarkModeSoon;

  /// No description provided for @settingsLogoutTitle.
  ///
  /// In ar, this message translates to:
  /// **'تسجيل الخروج من مزادك؟'**
  String get settingsLogoutTitle;

  /// No description provided for @settingsLogout.
  ///
  /// In ar, this message translates to:
  /// **'تسجيل الخروج'**
  String get settingsLogout;

  /// No description provided for @settingsDeleteConfirmTitle.
  ///
  /// In ar, this message translates to:
  /// **'اكتب DELETE للتأكيد'**
  String get settingsDeleteConfirmTitle;

  /// No description provided for @settingsDeleteConfirmHint.
  ///
  /// In ar, this message translates to:
  /// **'DELETE'**
  String get settingsDeleteConfirmHint;

  /// No description provided for @settingsAccountDeleted.
  ///
  /// In ar, this message translates to:
  /// **'تم طلب حذف الحساب'**
  String get settingsAccountDeleted;

  /// No description provided for @settingsDebugInfo.
  ///
  /// In ar, this message translates to:
  /// **'معلومات التشخيص'**
  String get settingsDebugInfo;

  /// No description provided for @noActiveListings.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد قوائم نشطة'**
  String get noActiveListings;

  /// No description provided for @noEndedListings.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد قوائم منتهية'**
  String get noEndedListings;

  /// No description provided for @noDrafts.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مسودات'**
  String get noDrafts;

  /// No description provided for @noPendingReviews.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مراجعات معلقة'**
  String get noPendingReviews;

  /// No description provided for @noActiveAuctions.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مزادات نشطة'**
  String get noActiveAuctions;

  /// No description provided for @noEndedAuctions.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مزادات منتهية'**
  String get noEndedAuctions;

  /// No description provided for @noAuctionsWon.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مزادات فائزة بعد'**
  String get noAuctionsWon;

  /// No description provided for @noActiveBids.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مزايدات نشطة'**
  String get noActiveBids;

  /// No description provided for @noWinsYet.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد انتصارات بعد'**
  String get noWinsYet;

  /// No description provided for @noLostBids.
  ///
  /// In ar, this message translates to:
  /// **'لا توجد مزايدات خاسرة'**
  String get noLostBids;

  /// No description provided for @watchlistEmpty.
  ///
  /// In ar, this message translates to:
  /// **'قائمة المتابعة فارغة'**
  String get watchlistEmpty;

  /// No description provided for @removedFromWatchlist.
  ///
  /// In ar, this message translates to:
  /// **'تمت الإزالة من قائمة المتابعة'**
  String get removedFromWatchlist;

  /// No description provided for @cannotEditWithBids.
  ///
  /// In ar, this message translates to:
  /// **'لا يمكن تعديل القائمة بوجود مزايدات نشطة'**
  String get cannotEditWithBids;

  /// No description provided for @endListingEarly.
  ///
  /// In ar, this message translates to:
  /// **'إنهاء القائمة مبكراً؟'**
  String get endListingEarly;

  /// No description provided for @endNow.
  ///
  /// In ar, this message translates to:
  /// **'إنهاء الآن'**
  String get endNow;

  /// No description provided for @editListing.
  ///
  /// In ar, this message translates to:
  /// **'تعديل القائمة'**
  String get editListing;

  /// No description provided for @endEarly.
  ///
  /// In ar, this message translates to:
  /// **'إنهاء مبكر'**
  String get endEarly;

  /// No description provided for @viewAnalytics.
  ///
  /// In ar, this message translates to:
  /// **'عرض الإحصائيات'**
  String get viewAnalytics;

  /// No description provided for @linkCopied.
  ///
  /// In ar, this message translates to:
  /// **'تم نسخ الرابط'**
  String get linkCopied;

  /// No description provided for @markAsRead.
  ///
  /// In ar, this message translates to:
  /// **'تعيين كمقروء'**
  String get markAsRead;

  /// No description provided for @notificationsTitle.
  ///
  /// In ar, this message translates to:
  /// **'الإشعارات'**
  String get notificationsTitle;

  /// No description provided for @bids.
  ///
  /// In ar, this message translates to:
  /// **'المزايدات'**
  String get bids;

  /// No description provided for @chat.
  ///
  /// In ar, this message translates to:
  /// **'المحادثة'**
  String get chat;

  /// No description provided for @chatHint.
  ///
  /// In ar, this message translates to:
  /// **'قل شيئاً...'**
  String get chatHint;

  /// No description provided for @noCommission.
  ///
  /// In ar, this message translates to:
  /// **'بدون عمولة'**
  String get noCommission;

  /// No description provided for @zakat.
  ///
  /// In ar, this message translates to:
  /// **'زكاة'**
  String get zakat;

  /// No description provided for @customAmountHint.
  ///
  /// In ar, this message translates to:
  /// **'مبلغ آخر'**
  String get customAmountHint;

  /// No description provided for @priceFrom.
  ///
  /// In ar, this message translates to:
  /// **'من {price} د.أ'**
  String priceFrom(String price);

  /// No description provided for @priceTo.
  ///
  /// In ar, this message translates to:
  /// **'حتى {price} د.أ'**
  String priceTo(String price);

  /// No description provided for @priceMin.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأدنى'**
  String get priceMin;

  /// No description provided for @priceMax.
  ///
  /// In ar, this message translates to:
  /// **'الحد الأقصى'**
  String get priceMax;

  /// No description provided for @clearAll.
  ///
  /// In ar, this message translates to:
  /// **'مسح الكل'**
  String get clearAll;

  /// No description provided for @applyFilters.
  ///
  /// In ar, this message translates to:
  /// **'تطبيق الفلاتر'**
  String get applyFilters;

  /// No description provided for @enterBidAmount.
  ///
  /// In ar, this message translates to:
  /// **'أدخل مبلغ المزايدة'**
  String get enterBidAmount;

  /// No description provided for @invalidAmount.
  ///
  /// In ar, this message translates to:
  /// **'مبلغ غير صالح'**
  String get invalidAmount;

  /// No description provided for @days30.
  ///
  /// In ar, this message translates to:
  /// **'٣٠ يوم'**
  String get days30;

  /// No description provided for @days60.
  ///
  /// In ar, this message translates to:
  /// **'٦٠ يوم'**
  String get days60;

  /// No description provided for @days90.
  ///
  /// In ar, this message translates to:
  /// **'٩٠ يوم'**
  String get days90;

  /// No description provided for @technicalProposalHint.
  ///
  /// In ar, this message translates to:
  /// **'أدخل العرض الفني أو الملاحظات...'**
  String get technicalProposalHint;

  /// No description provided for @duration1h.
  ///
  /// In ar, this message translates to:
  /// **'ساعة'**
  String get duration1h;

  /// No description provided for @duration3h.
  ///
  /// In ar, this message translates to:
  /// **'٣ ساعات'**
  String get duration3h;

  /// No description provided for @duration6h.
  ///
  /// In ar, this message translates to:
  /// **'٦ ساعات'**
  String get duration6h;

  /// No description provided for @duration12h.
  ///
  /// In ar, this message translates to:
  /// **'١٢ ساعة'**
  String get duration12h;

  /// No description provided for @duration24h.
  ///
  /// In ar, this message translates to:
  /// **'٢٤ ساعة'**
  String get duration24h;

  /// No description provided for @duration3d.
  ///
  /// In ar, this message translates to:
  /// **'٣ أيام'**
  String get duration3d;

  /// No description provided for @duration7d.
  ///
  /// In ar, this message translates to:
  /// **'٧ أيام'**
  String get duration7d;

  /// No description provided for @jod.
  ///
  /// In ar, this message translates to:
  /// **'د.أ'**
  String get jod;

  /// No description provided for @currency.
  ///
  /// In ar, this message translates to:
  /// **'JOD'**
  String get currency;
}

class _SDelegate extends LocalizationsDelegate<S> {
  const _SDelegate();

  @override
  Future<S> load(Locale locale) {
    return SynchronousFuture<S>(lookupS(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['ar', 'en'].contains(locale.languageCode);

  @override
  bool shouldReload(_SDelegate old) => false;
}

S lookupS(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar':
      return SAr();
    case 'en':
      return SEn();
  }

  throw FlutterError(
      'S.delegate failed to load unsupported locale "$locale". This is likely '
      'an issue with the localizations generation tool. Please file an issue '
      'on GitHub with a reproducible sample app and the gen-l10n configuration '
      'that was used.');
}
