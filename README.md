# M_TSE v1.2.0 | کتابخانه اطلاعات بازار بورس تهران

پکیج قابل نصب پایتون برای **دیده‌بان برخط بازار، قراردادهای مشتقه، تاریخچه قیمت تعدیل‌شده و نشده، نگهداری شناسه نمادها و ذخیره دائمی قیمت روزانه در SQLite**.

- منبع پیش‌فرض: **API جدید TSETMC** (`cdn.tsetmc.com`). سایت قدیم (`old.tsetmc.com`) فقط به‌عنوان جایگزین اختیاری (`market_source="old"` یا `"auto"`) نگه داشته شده.
- `Close` = قیمت پایانی (`pClosing`) و `Last` = آخرین معامله (`pDrCotVal`)، با نام یکسان در همه ماژول‌ها.
- شناسه‌ها همیشه متن هستند؛ خروجی Excel شناسه‌ها را به‌صورت سلول متنی می‌نویسد.
- نام نمادها با «ی» و «ک» فارسی یکسان‌سازی می‌شوند؛ جست‌وجوی `خودرو`، `فملي` یا `بهین‌رو` بدون حساسیت به حروف عربی و نیم‌فاصله کار می‌کند.
- نگهداری روزهای بدون معامله انتخاب کاربر است (`traded_only`)؛ پیش‌فرض: همه روزها نگه داشته می‌شوند.

> وضعیت راستی‌آزمایی: پارسرها روی نمونه پاسخ‌های واقعی ضبط‌شده از TSETMC (سایت جدید و قدیم) و ۳۰ آزمون آفلاین بررسی شده‌اند. اتصال زنده به TSETMC از محیط ساخت ممکن نبود؛ قبل از استفاده عملیاتی، آزمون میدانی در `docs/LIMITATIONS_FA.md` را اجرا کنید.

## نصب روی Windows / Python 3.10+

1. فایل ZIP را از حالت فشرده خارج کنید.
2. `install_windows.bat` را اجرا کنید، یا داخل پوشه پروژه:

```powershell
py -m pip install .
mtse --data-dir .\tse_data init
mtse --data-dir .\tse_data status
```

اگر دستور `mtse` در PATH نبود: `py -m M_TSE --data-dir .\tse_data status`.

## نمونه سریع پایتون

```python
from M_TSE import M_TSE

tse = M_TSE(data_dir="./tse_data")                  # market_source="new" پیش‌فرض
market = tse.market.snapshot(depth=True)            # همه ردیف‌های آنلاین + عمق ۵ سطح
stocks = tse.market.by_type("Stock")                # سهام
calls = tse.derivatives.calls()                     # اختیار خرید با سررسید و دارایی پایه
puts = tse.derivatives.puts()                       # اختیار فروش
futures = tse.derivatives.futures()                 # آتی/مشتقات کالایی
expired = tse.archive.option_contracts()            # تمام قراردادهای اختیار آرشیوی
raw = tse.history.fetch(ticker="خودرو")             # تاریخچه خام (همه روزها)
traded = tse.history.fetch(ticker="خودرو", traded_only=True)   # فقط روزهای دارای معامله
adjusted = tse.history.fetch(ticker="خودرو", adjusted=True)
tse.update_tda()                                    # نگهداری شناسه‌های قدیم و جدید
report = tse.backfill(workers=3, min_hours=12)      # آرشیو همه شناسه‌ها؛ طولانی
cached = tse.archive.history("65883838195688438")   # از SQLite بدون اینترنت؛ شناسه = متن
```

**نکته:** اگر نمادی چند شناسه دارد، `ticker=` خطای `AmbiguousTicker` می‌دهد؛ با `instrument_id="..."` شناسه را صریحاً تعیین کنید.

## ساختار پروژه

- `src/M_TSE`: کد قابل نصب با CLI (`mtse`) و اجزای مستقل
- `src/M_TSE/data/Ticker Data Archive.xlsx`: فایل پایه TDA (۶٬۹۴۹ شناسه)
- `docs/USER_GUIDE_FA.md`: راهنمای نصب/اجرا/بازیابی/پشتیبان‌گیری
- `docs/API_FA.md`: مرجع توابع، قرارداد نام ستون‌ها و endpointها
- `docs/ARCHITECTURE_FA.md`: معماری و سیاست ماندگاری داده
- `docs/LIMITATIONS_FA.md`: پوشش داده، تعدیل و مواردی که آنلاین تأیید نشده
- `examples/`، `notebooks/`، `tests/`

## CLI

```powershell
mtse --data-dir .\tse_data update-tda
mtse --data-dir .\tse_data watch --type Stock --depth --out stocks.xlsx
mtse --data-dir .\tse_data options --kind both --out options.xlsx
mtse --data-dir .\tse_data sync --id 65883838195688438 --with-adjustments
mtse --data-dir .\tse_data sync --all --workers 3 --min-hours 12
mtse --data-dir .\tse_data history --id 65883838195688438 --adjusted --out price.xlsx
mtse --source auto --data-dir .\tse_data watch --limit 5
mtse --data-dir .\tse_data backup --output archive_backup.sqlite
```

خروجی `.xlsx` شناسه‌ها را سالم نگه می‌دارد؛ اگر CSV را در Excel باز کنید، Excel شناسه‌های بلند را خراب می‌کند.

## اجرای آزمون‌ها

```powershell
py -m pip install ".[test]"
py -m pytest -q
```

## ارتقا از TSEMarketKit 1.0

- `from M_TSE import M_TSE` (نام قدیمی `TSEMarketKit` هم به‌عنوان نام مستعار کار می‌کند).
- پایگاه SQLite قبلی در اولین اجرا خودکار به ساختار جدید ارتقا می‌یابد و نسخه قبلی با پسوند `.v1-backup.sqlite` کنارش حفظ می‌شود.
- جدول تبدیل نام ستون‌ها در `CHANGELOG.md` آمده است.

## اجرای روزانه

پس از آزمایش آنلاین روی چند نماد، `daily_sync_windows.bat` را از Task Scheduler فراخوانی کنید. اسکریپت `examples/daily_archive.py` (با `market_source="auto"`) شناسه‌ها را به‌روزرسانی، همه تاریخچه‌های قابل دستیابی را در SQLite ذخیره و از پایگاه بکاپ تهیه می‌کند. هیچ اجرای خودکاری صرفاً با نصب پکیج فعال نمی‌شود.
