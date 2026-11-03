# تغییرات

## 1.2.0 — 2026-11-03

- اگر `data_dir` داده نشود، بار اول از کاربر پرسیده می‌شود آرشیو کجا ذخیره شود و مسیر در `~/.m_tse/config.json` ذخیره می‌شود؛ دفعه‌های بعد بدون سؤال از همان پوشه استفاده می‌شود.
- `set_data_dir(path)` / `get_data_dir()` و فرمان `mtse set-dir <path>` برای تغییر پوشه.

## 1.1.0 — 2026-11-03 (M_TSE)

### تغییر نام
- نام کتابخانه: `M_TSE` (`from M_TSE import M_TSE`). فرمان CLI: `mtse` یا `py -m M_TSE`.
- `TSEMarketKit` به‌عنوان نام مستعار `M_TSE` باقی مانده است.

### منبع داده: سایت جدید TSETMC
- دیده‌بان بازار و عمق ۵ سطح از `cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch`.
- شاخص و آمار کل بازار از `MarketData/GetMarketOverview/1` و `/2` (بورس و فرابورس)، به‌همراه `LastTradeDate` و وضعیت بازار.
- `Type` و `MarketType` که API جدید برنمی‌گرداند، از آرشیو محلی و برای شناسه‌های تازه از `Instrument/GetInstrumentInfo` تکمیل می‌شوند.
- `market_source="new" | "old" | "auto"`؛ سایت قدیم فقط جایگزین اختیاری است.
- 403 به خطاهای قابل تکرار اضافه شد؛ هدرهای Referer/Origin سایت TSETMC ارسال می‌شوند.

### شناسه‌ها (IndexURL)
- همه‌جا متن؛ شناسه float با خطای روشن رد می‌شود.
- `import_tda` سلول‌هایی را که شناسه در آن‌ها به‌صورت عدد ذخیره شده (و احتمالاً خراب شده) وارد نمی‌کند و در `rejected` گزارش می‌دهد.
- `export_tda` و تابع جدید `to_excel` شناسه‌ها و کدها را سلول متنی (`@`) می‌نویسند. CLI با `--out file.xlsx` از همین روش استفاده می‌کند.

### یکسان‌سازی ی/ک
- `Ticker` و `Name` هنگام ورود (snapshot، TDA، آرشیو) با «ی» و «ک» فارسی ذخیره و برگردانده می‌شوند.
- `ticker_key` برای تطبیق، بدون حساسیت به فاصله و نیم‌فاصله.
- **رفع باگ:** تطبیق دارایی پایه اختیارها برای نمادهایی که در TSETMC با «ي»/«ك» عربی ثبت شده‌اند (مثل فملی) قبلاً ناموفق بود.

### نام ستون‌ها (یکسان در بازار، مشتقات و تاریخچه)

| نسخه 1.0 (snapshot) | نسخه 1.0 (تاریخچه) | نسخه 1.1 | منبع |
|---|---|---|---|
| `First` | `Open` | `Open` | pf / priceFirst |
| `Max` / `Min` | `High` / `Low` | `High` / `Low` | pmx,pmn / priceMax,priceMin |
| `Final` | `Final` | **`Close`** | pcl / pClosing (قیمت پایانی) |
| `Last` | `Close` | **`Last`** | pdv / pDrCotVal (آخرین معامله) |
| `Yesterday` | `Y-Final` | `PrevClose` | py / priceYesterday |
| `Transaction` | `No` | `Trades` | ztt / zTotTran |
| `UnderlyingFinal` | — | `UnderlyingClose` | |
| — | `AdjFinal` / `AdjClose` / `AdjY-Final` | `AdjClose` / `AdjLast` / `AdjPrevClose` | |

- ستون جدید `JDate` (تاریخ شمسی) در تاریخچه.
- پایگاه SQLite نسخه 1.0 خودکار ارتقا می‌یابد (`final→close`، `close→last`، `yesterday→prev_close`) و نسخه قبلی با پسوند `.v1-backup.sqlite` حفظ می‌شود.

### روزهای بدون معامله: انتخاب کاربر
- `traded_only` در سازنده (پیش‌فرض کتابخانه) و در `history.fetch`، `backfill`، `sync`، `archive.sync_one/sync_many/history` و CLI (`--traded-only`).
- پیش‌فرض: **همه روزها ذخیره می‌شوند** (نسخه 1.0 روزهای بدون معامله را بی‌برگشت حذف می‌کرد).
- `archive.coverage()`: اولین/آخرین تاریخ، تعداد ردیف و روزهای دارای معامله هر شناسه.

### سایر
- نوشتن در SQLite از مسیر یک قفل واحد برای workerهای موازی.
- آزمون‌ها: ۳۰ آزمون آفلاین، به‌علاوه بررسی پارسرها روی نمونه پاسخ‌های واقعی ضبط‌شده از TSETMC.

### بدون تغییر (عمداً)
- استخراج دارایی پایه، قیمت اعمال و سررسید اختیارها همچنان از روی نام قرارداد انجام می‌شود (برای مرحله بعد).

## 1.0.0 — 2026-11-02 (TSEMarketKit)

- نسخه اولیه: دیده‌بان old.tsetmc.com، مشتقات، تاریخچه، آرشیو SQLite، TDA تک‌شیت، CLI `tsemarket`.
