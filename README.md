# Python Android

Pinned Android native builds for CPython 3.10, Chaquopy 17.1.0 and third-party wheels. Supports API 24, arm64-v8a and armeabi-v7a.

## Build and release

Source revisions and hashes are pinned in `native/sources.json` and `native/runtime-sources.json`. Build tools and commands are defined in `.github/workflows/build.yml`.

Push a `v*` tag to build both ABIs and publish a GitHub Release. Manual workflow runs produce Actions artifacts only.

Each release contains 12 wheels, 2 native ZIPs and 2 provenance manifests. Binary artifacts stay outside Git.

## TV integration

TV pins the release and manifest hashes in `chaquo/runtime/native.lock.json`. From the TV repository, run `python scripts/sync_python_runtime.py` before building the Python AAR and module APK.

TV owns Java SDK integration, helpers, canonical C++ runtime selection and final packaging. Native release versions are independent of TV module versions.

## Verification

Builds check SHA-256, ABI, dependencies and 16 KB ELF LOAD/RELRO alignment. Consumers report device loading, physical ARM and native 16 KB tests separately.
