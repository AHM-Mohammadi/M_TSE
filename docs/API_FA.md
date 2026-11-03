# مرجع API — M_TSE 1.2.0

تمام خروجی‌های جدولی `pandas.DataFrame` هستند. نام متغیرها و ماژول‌ها عمداً انگلیسی و سازگار با اکوسیستم Python انتخاب شده‌اند.

## ۱. کلاس مرکزی `M_TSE`

```python
from M_TSE import M_TSE
tse = M_TSE(data_dir="./tse_data", timeout=18, retries=3, min_interval=0.2,
            market_source="new", traded_only=False, client=None, seed=True, enrich=True)
```

- `data_dir`: پوشه فیزیکی فایل‌های SQLite و TDA.
- `timeout`: حداکثر زمان هر درخواست (ثانیه).
- `retries`: تعداد تلاش مجدد برای خطاهای قابل تکرار.
- `min_interval`: حداقل فاصله درخواست‌های HTTP در یک نمونه Client؛ پیش‌فرض ۰٫۲ ثانیه.
- `client`: ابزار HTTP جایگزین برای تست، یا اتصال سفارشی.
- `seed`: در پایگاه خالی، آرشیو TDA همراه بسته را وارد کند (پیش‌فرض true).
- `market_source`: منبع دیده‌بان بازار. `"new"` (پیش‌فرض) API جدید `cdn.tsetmc.com` است. `"old"` سایت قدیم `old.tsetmc.com` است. `"auto"` اول API جدید را امتحان می‌کند و اگر جواب نداد سراغ سایت قدیم می‌رود.
- `traded_only`: پیش‌فرض کل کتابخانه برای روزهای بدون معامله. با `False` (پیش‌فرض) همه روزها نگهداری و ذخیره می‌شوند؛ با `True` روزهای بدون معامله کنار گذاشته می‌شوند. همه متدهای تاریخچه هم پارامتر `traded_only=` دارند و مقدار پیش‌فرض را برای همان فراخوانی عوض می‌کنند.
- `enrich`: در API جدید، نوع ابزار (`Type`) و بازار (`MarketType`) در پاسخ دیده‌بان وجود ندارد. این مقادیر اول از آرشیو محلی خوانده می‌شوند و برای شناسه‌های تازه، یک بار از `GetInstrumentInfo` گرفته می‌شوند.

ویژگی‌ها: `tse.client`، `tse.market`، `tse.derivatives`، `tse.history`، `tse.archive`.

متدها:

```python
tse.update_tda()  # dict: received, added, total
tse.backfill(ids=None, types=None, workers=3, min_hours=0,
             refresh_adjustments=False, progress=None, traded_only=None)  # DataFrame
tse.sync("65883838195688438", refresh_adjustments=False, traded_only=None)  # dict
tse.stored_history("65883838195688438", adjusted=False, start=None, end=None, traded_only=None)
```

`traded_only=None` یعنی از پیش‌فرض تعیین‌شده در سازنده استفاده شود.

## ۱-۱. قرارداد نام ستون‌ها (در همه ماژول‌ها یکسان)

| ستون | معنا | فیلد API جدید | فیلد تاریخچه |
|---|---|---|---|
| `Open` | اولین قیمت معامله روز | `pf` | `priceFirst` |
| `High` / `Low` | بیشترین / کمترین قیمت روز | `pmx` / `pmn` | `priceMax` / `priceMin` |
| `Close` | **قیمت پایانی**: میانگین وزنی قیمت معاملات روز که مبنای قیمت روز بعد است | `pcl` | `pClosing` |
| `Last` | آخرین قیمت معامله‌شده | `pdv` | `pDrCotVal` |
| `PrevClose` | قیمت پایانی روز قبل | `py` | `priceYesterday` |
| `Trades` / `Volume` / `Value` | تعداد معاملات / حجم / ارزش | `ztt` / `qtj` / `qtc` | `zTotTran` / `qTotTran5J` / `qTotCap` |

ستون `Close` در این نسخه همان قیمت پایانی است. برای همین با کتابخانه‌های تحلیل تکنیکال (pandas-ta، backtrader و…) که `Close` را قیمت پایانی فرض می‌کنند، درست کار می‌کند. جدول تبدیل نام‌های نسخه 1.0 در `CHANGELOG.md` آمده است.

## ۲. بازار `tse.market`

| فراخوانی | کاربرد |
|---|---|
| `snapshot(depth=False, numeric=True)` | تمام نمادهای موجود در آخرین snapshot TSETMC |
| `snapshot(depth=True)` | همان اطلاعات با ۵ سطح عمق سفارش، در صورت وجود |
| `by_type("Stock")` | فیلتر سهام |
| `by_type(["Fund", "CommodityFund"])` | فیلتر صندوق‌ها |
| `by_type("311")` | فیلتر کد عددی نوع |
| `by_type("Stock", primary_board_only=True)` | فیلتر انتخابی با IRcode ختم‌شونده به ۱ |
| `overview()` | شاخص‌ها و آمار تجمیعی بازار در یک DataFrame |

فهرست دسته‌ها: `Sukuk`, `Stock`, `CorporateBond`, `Future`, `Fund`, `Akhza`, `Teseh`, `Salf`, `CallOption`, `PutOption`, `CommodityFund`, `Priority`, `CommodityDerivative`, `Morabehe`.

**ستون‌های اصلی snapshot:** `IndexURL` (index)، `IRcode`، `Ticker`، `Name`، `LastTrade`، `Open`، `Close`، `Last`، `Trades`، `Volume`، `Value`، `Low`، `High`، `PrevClose`، `EPS`، `BaseVolume`، `IDK_1`، `MarketType`، `Industry`، `MaxAlw`، `MinAlw`، `StockQty`، `Type`، `Nav`، `OpenInterest`. دو ستون آخر ممکن است برای برخی نمادها یا پاسخ‌ها خالی باشند. `Ticker` و `Name` همیشه با حروف فارسی «ی» و «ک» برگردانده می‌شوند.

`snapshot(source="old")` یا `overview(source="auto")` منبع را فقط برای همان فراخوانی عوض می‌کند. `tse.market.last_source` نشان می‌دهد آخرین داده از کدام منبع آمده است.

`overview()` در API جدید این ستون‌ها را برمی‌گرداند: `LastTradeDate`، `TSE_Situation`، `TEPIX`، `TEPIXChange`، `TEPIX_EW`، `TEPIX_EWChange`، `TSE_MarketCap`، `TSE_Volume`، `TSE_Value`، `TSE_NumTransaction`، `TSE_LastTradeTime`، و همین ستون‌ها برای فرابورس با پیشوند `IFB_` (به‌همراه `IFX`، `IFXChange`). از `LastTradeDate` می‌شود فهمید داده snapshot مال کدام روز معاملاتی است.

**عمق سفارش:** `BuyPrice1`، `SellPrice1`، `BuyVolume1`، `SellVolume1`، `BuyCount1`، `SellCount1` و همین الگو برای سطوح ۲ تا ۵؛ مقادیر مفقود `NaN` هستند، نه الزاماً صفر.

## ۳. مشتقات `tse.derivatives`

```python
tse.derivatives.calls(depth=True, underlying=True)
tse.derivatives.puts(depth=True, underlying=True)
tse.derivatives.options(kind="both", depth=True, underlying=True, today=None)
tse.derivatives.futures(depth=True)
```

`kind` یکی از `both`, `call`, `put` است. `today` از نوع `datetime.date` برای تست یا بررسی DTE در تاریخ ثابت استفاده می‌شود.

**ستون‌های افزوده‌شده گزینه‌ها:**

- `OptionKind`: call/put.
- `Underlying`: نام نماد پایه استنباط‌شده از نام ابزار.
- `Strike`: قیمت اعمال طبق متن نام قرارداد.
- `Expiry`: تاریخ سررسید میلادی (`datetime.date`).
- `DaysToExpiry`: تعداد روز تقویمی با تاریخ today؛ روزهای تعطیل نیز شمرده می‌شوند.
- `UnderlyingID`: شناسه پایه در snapshot فعلی (در صورت تطبیق).
- `UnderlyingClose`، `UnderlyingLast`، `UnderlyingVolume`: اطلاعات مبنا در همان snapshot.

تطبیق دارایی پایه با کلید یکسان‌شده انجام می‌شود (بدون حساسیت به ی/ي، ک/ك، فاصله و نیم‌فاصله).

*پارسر نام قرارداد فقط الگوهای `متن-قیمت اعمال-تاریخ شمسی` را می‌خواند. مقدار NaN در این ستون‌ها به معنای نبود ابزار نیست، بلکه نشان می‌دهد مشخصات آن قابل استخراج قطعی از نام نیست.*

## ۴. تاریخچه آنلاین `tse.history`

```python
tse.history.resolve(ticker="خودرو")
tse.history.resolve(instrument_id="65883838195688438")
tse.history.fetch(ticker=None, instrument_id="...", adjusted=False,
                  last=0, traded_only=None, include_metadata=True)
tse.history.fetch_many(tickers=None, instrument_ids=["...", "..."],
                       adjusted=False, workers=4, on_error="raise")
```

`last=0` مطابق کد اولیه کاربر به سرویس TSETMC ارسال می‌شود؛ هیچ تضمینی درباره معنای فنی متغیر `last` فراتر از همین نحوه ارسال ادعا نشده است. با `traded_only=True` روزهای دارای `zTotTran=0` از پاسخ حذف می‌شوند. پیش‌فرض (`None` ← مقدار سازنده، یعنی `False`) همه روزها را نگه می‌دارد.

ستون‌های خام: `Date` (میلادی)، `JDate` (شمسی، مثل `1405/08/12`)، `Open`، `High`، `Low`، `Close`، `Last`، `PrevClose`، `Volume`، `Value`، `Trades`، `IndexURL`. در صورت وجود شناسه در TDA، ستون‌های `Ticker`, `Name`, `MarketType`, `Industry`, `Type`, `StockQty` افزوده می‌شوند.

ستون‌های تعدیل: `AdjCoef`، `AdjOpen`، `AdjHigh`، `AdjLow`، `AdjClose`، `AdjLast`، `AdjPrevClose`.

- `Close` = `pClosing` (قیمت پایانی).
- `Last` = `pDrCotVal` (قیمت آخرین معامله).
- `on_error="raise"`: برای خطای هر نماد، کل عملیات گروهی با خطا خاتمه می‌یابد.
- `on_error="skip"`: فقط داده‌های موفق بازگردانده می‌شوند و دلایل خطا از `tse.history.last_errors` قابل مشاهده‌اند.

## ۵. آرشیو `tse.archive`

| متد | خروجی / توضیح |
|---|---|
| `instruments(types=None)` | DataFrame تمام شناسه‌های آرشیوشده (حتی منقضی) |
| `option_contracts(kind="both", today=None)` | همه اختیارهای شناخته‌شده (حتی منقضی) و مشخصات قابل استخراج از نام |
| `find(ticker)` | همه شناسه‌های مربوط به یک نماد؛ بدون حساسیت به ی/ي، ک/ك، فاصله و نیم‌فاصله |
| `import_tda(path=None)` | افزودن/به‌روزرسانی آرشیو پایه از یک Excel حاوی TDA؛ ردیف‌هایی که شناسه‌شان در Excel به‌صورت عدد ذخیره شده (و احتمالاً خراب شده) وارد نمی‌شوند و در `result["rejected"]` گزارش می‌شوند |
| `merge_instruments(df)` | ثبت دیتا با کلید IndexURL، بدون حذف قبلی‌ها |
| `update_tda(tse.market)` | دریافت snapshot و ثبت در آرشیو + خروجی Excel |
| `export_tda(path=None)` | نوشتن فایل Excel با فقط شیت TDA؛ شناسه‌ها و کدها به‌صورت سلول متنی |
| `sync_one(iid, tse.client, refresh_adjustments=False, min_hours=0, last=0, traded_only=False)` | به‌روزرسانی تاریخچه یک شناسه؛ dict نتیجه |
| `sync_many(tse.client, ids=None, types=None, workers=4, min_hours=0, refresh_adjustments=False, progress=None, last=0, traded_only=False)` | گزارش نتایج چند نماد؛ DataFrame |
| `history(iid, adjusted=False, start=None, end=None, traded_only=False)` | بازیابی تاریخچه بدون شبکه، تاریخ‌های start/end میلادی؛ `traded_only=True` روزهای بدون معامله را فقط در خروجی پنهان می‌کند |
| `coverage(ids=None)` | اولین و آخرین تاریخ ذخیره‌شده، تعداد ردیف و تعداد روزهای دارای معامله برای هر شناسه |
| `sync_report()` | ریز وضعیت آخرین تلاش نمادها |
| `stats()` | آمار تعداد شناسه‌ها، ردیف‌های قیمت، موفق/ناموفق |
| `count_instruments()` / `count_prices()` | اعداد شمارش |
| `backup(destination)` | پشتیبان‌گیری سازگار با WAL در SQLite |

در آرشیو تاریخی، کلید یکتا `(instrument_id, date)` است. عملیات `sync_one` با پاسخ خطای سرور، داده‌های گذشته را حذف نمی‌کند. دریافت موفق داده خالی برای یک نماد، وضعیت `empty` ایجاد می‌کند.

### تابع progress

```python
def report_progress(done, total, result):
    if done % 20 == 0 or result['status'] == 'failed':
        print(done, '/', total, result['id'], result['status'])

result = tse.backfill(ids=["..."], workers=2, progress=report_progress)
```

## ۶. اتصال سفارشی / تنظیم مسیر API

```python
from M_TSE import TSETMCClient, M_TSE
client = TSETMCClient(timeout=25, retries=2, min_interval=0.4, market_source="auto")
tse = M_TSE(data_dir="./tse_data", client=client)
```

Endpointهای پیش‌فرض (همه روی `https://cdn.tsetmc.com/api`):

| کاربرد | مسیر |
|---|---|
| دیده‌بان بازار + عمق ۵ سطح | `ClosingPrice/GetMarketWatch?market=0&...&withBestLimits=true` |
| شاخص و آمار کل بازار | `MarketData/GetMarketOverview/1` (بورس) و `/2` (فرابورس) |
| مشخصات نماد (Type, flow, صنعت) | `Instrument/GetInstrumentInfo/{insCode}` |
| تاریخچه روزانه | `ClosingPrice/GetClosingPriceDailyList/{insCode}/0` |
| ضرایب تعدیل | `ClosingPrice/GetPriceAdjustList/{insCode}` |

سایت قدیم (`old.tsetmc.com/tsev2/data/MarketWatchInit.aspx`) فقط برای `market_source="old"` یا `"auto"` استفاده می‌شود. همه مسیرها با پارامترهای `market_watch_url`، `overview_base`، `instrument_info_base`، `market_url`، `history_base` و `adjust_base` قابل تغییرند. پاسخ 403 هم جزو خطاهای قابل تکرار است، چون TSETMC زیر بار گاهی 403 برمی‌گرداند. این گزینه‌ها برای رفع تغییر دامنه/پروتکل پیش‌بینی شده‌اند؛ URL جایگزین بدون صحت‌سنجی نباید وارد شود.

## ۷. مدیریت خطا

- `TSEMarketError`: کلاس پایه.
- `DataSourceError`: خطای درخواست HTTP، JSON یا فرمت داده، یا نداشتن ضریب تعدیل آفلاین.
- `InstrumentNotFound`: نماد متنی در آرشیو یافت نشد.
- `AmbiguousTicker`: شناسه‌های متفاوت برای یک ticker؛ برای جلوگیری از نسبت‌دادن اشتباه قیمت به ابزار قدیمی.
- `ValueError`: پارامتر نامعتبر یا نوع نماد ناشناخته.

## ۸. شناسه‌ها و Excel

شناسه‌ها (`IndexURL`) عدد ۱۴ تا ۱۹ رقمی هستند و در همه جای کتابخانه **متن** (str) نگهداری می‌شوند. Excel و نوع float فقط حدود ۱۵ رقم دقت دارند؛ مثلاً `65883838195688438` به `65883838195688432` تبدیل می‌شود و دیگر قابل تشخیص نیست.

- شناسه را همیشه به‌صورت رشته بدهید: `instrument_id="65883838195688438"`. عدد صحیح پایتون (int) هم پذیرفته می‌شود؛ float رد می‌شود.
- برای خروجی‌ای که در Excel باز می‌شود، از `to_excel` استفاده کنید، نه CSV:

```python
from M_TSE import to_excel
to_excel(tse.derivatives.calls(), "calls.xlsx")   # IndexURL / UnderlyingID به‌صورت متن
```

- اگر CSV را دوباره در pandas می‌خوانید: `pd.read_csv(path, dtype={"IndexURL": str})`.
- در CLI، اگر پسوند فایل خروجی `.xlsx` باشد، همین روش امن خودکار استفاده می‌شود: `--out calls.xlsx`.

## ۹. یکسان‌سازی متن

- `normalize(text)`: ي/ى ← ی، ك ← ک، ارقام فارسی/عربی ← لاتین، حذف کشیده و اعراب، حذف نیم‌فاصله کنار فاصله، و یکی کردن فاصله‌ها. نیم‌فاصله داخل کلمه حفظ می‌شود.
- `ticker_key(text)`: کلید تطبیق؛ نسخه `normalize` بدون هیچ فاصله و نیم‌فاصله‌ای.
- `Ticker` و `Name` هنگام ورود به آرشیو و در خروجی snapshot یکسان‌سازی می‌شوند. پایگاه‌های نسخه 1.0 هنگام اولین اجرا خودکار ارتقا داده می‌شوند و از فایل قبلی یک نسخه `.v1-backup.sqlite` کنارش نگه داشته می‌شود.

## ۱۰. مثال ثبت خروجی

```python
calls = tse.derivatives.calls()
calls.to_parquet("calls.parquet")  # نیازمند pyarrow یا fastparquet
tse.archive.history("...", adjusted=False).to_csv("history.csv", index=False, encoding="utf-8-sig")
to_excel(tse.archive.history("..."), "history.xlsx", index=False)
```

`to_parquet` یک توانایی Pandas و وابسته به نصب اختیاری موتور Parquet است؛ خود بسته نیاز قطعی به pyarrow ندارد.
