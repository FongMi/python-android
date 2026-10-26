# Python Android 原生建置

建置 Android API 24 的 CPython 3.10、Chaquopy 17.1.0 native runtime 與第三方 wheels，提供 arm64-v8a／armeabi-v7a。TV 保留 Java SDK、helpers、canonical C++ runtime 整合、AAR 與模組 APK 封裝。

## 原生建置

`native/sources.json` 固定 wheel 來源、Chaquopy commit、CPython target、Rust 與 libffi 輸入雜湊；`native/runtime-sources.json` 固定 CPython、Chaquopy JNI 及其來源依賴。控制工具使用 Linux x86_64、Python 3.10／3.11；所有 Android extension 都使用 Python 3.10。

```sh
python native/build.py --abi arm64-v8a --chaquopy /path/to/chaquopy
python native/runtime-build.py --abi arm64-v8a --chaquopy /path/to/chaquopy-17.1.0 --source-deps /path/to/cpython-android-source-deps
```

ARM32 改用 `armeabi-v7a`。每個 ABI 使用新的 checkout；工具與版本準備方式見 `.github/workflows/build.yml`。連結器使用 `max-page-size=16384` 與 `common-page-size=16384`，驗證 ELF ABI、LOAD、RELRO、依賴與雜湊。

`chaquopy.patch` 修正 stable ABI 開發用連結與 Rust 的 CPython 庫選擇。cryptography 使用 `abi3-py310` 及官方 `CRYPTOGRAPHY_BUILD_OPENSSL_NO_LEGACY` 設定。libxml2／libxslt patches 保留 Android 匯出契約及正確的 callback const 型別；`libxml2-build.sh` 靜態連結固定來源的 xz，保留壓縮 XML 能力。

## 原生產物發布

推送 `v*` tag 會執行雙 ABI 的 wheels 與 runtime 建置，全部成功後核對 provenance 並建立同名 GitHub Release。手動執行 workflow 只建置及上傳 Actions artifacts。原生產物版本與 TV Python 模組 APK 版本獨立。

Release 包含 12 個 wheels、2 個 native ZIP、`wheels-manifest.json` 與 `native-bundles-manifest.json`。manifest 記錄 producer commit、run、tag、來源、ABI、檔案及每個 ELF 的 SHA-256。原生二進位不存入 Git。

TV 以 lock 檔固定 Release 與 manifest 雜湊，明確同步到忽略的本地產物目錄，再執行 AAR → Python 模組 APK 建置。一般 Gradle 建置不下載原生產物或觸發原生 CI。

## 驗證界線

原生建置與靜態 16 KB 對齊檢查不代替 App、實體 ARM 或原生 16 KB 裝置測試。TV 的消費端負責 shared C++、最終封裝、cryptography／runtime 回歸及實際載入驗證。
