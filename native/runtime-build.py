import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from build import DIRECTORY, download, run
from verify import verify_library


def verify_checkout(path, expected):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()
    if revision != expected:
        raise ValueError(f"Unexpected source revision: {path}")


def configure_linker(path, ndk):
    original = path.read_text()
    updated = original.replace('-Wl,-z,max-page-size=16384"', '-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384"')
    if updated == original:
        raise ValueError(f"Unexpected linker configuration: {path}")
    updated, count = re.subn(r"(?m)^ndk_version=\S+", "ndk_version=" + ndk, updated)
    if count != 1:
        raise ValueError(f"Unexpected NDK configuration: {path}")
    path.write_text(updated)


def build_dependencies(deps, lock, host, cache):
    for name, source in lock["sources"].items():
        if name == "python":
            continue
        directory = deps / name / "build" / source["version"]
        download(source["url"], directory / source["file"], source["sha256"])
        run("bash", str(deps / "build.sh"), name, source["version"], source["build"], host, cwd=deps)
        release = f"{name}-{source['version']}-{source['build']}"
        target = cache / release
        target.mkdir(parents=True, exist_ok=True)
        filename = f"{release}-{host}.tar.gz"
        shutil.copyfile(directory / host / filename, target / filename)


def compile_bridge(sdk, prefix, work, abi):
    runtime = sdk / "product/runtime"
    generated = work / "cython"
    generated.mkdir(parents=True)
    for directory, name in [("src/main/python/java", "chaquopy"), ("src/main/python", "chaquopy_java")]:
        output = generated / (name + ".c")
        run("cython", "-Wextra", "-Werror", name + ".pyx", "-I", str(generated), "-o", str(output), cwd=runtime / directory)
        content = output.read_text()
        content = re.sub(r"(?m)^__PYX_EXTERN_C (\w+)", r"__PYX_EXTERN_C JNIEXPORT \1 JNICALL", content)
        content = re.sub(r"(?m)^.*__pyx_insert_code_object\(c_line.*$", "", content)
        output.write_text(content)
    android = Path(os.environ["ANDROID_HOME"])
    cmake = android / "cmake/3.22.1/bin/cmake"
    native = work / "bridge"
    ndk = android / "ndk" / json.loads((DIRECTORY / "runtime-sources.json").read_text())["ndk"]
    run(str(cmake), "-S", str(runtime), "-B", str(native), "-GNinja", "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake", f"-DANDROID_ABI={abi}",
        "-DANDROID_PLATFORM=android-24", "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON",
        "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384",
        f"-DCHAQUOPY_SRC_DIR={generated}", "-DCHAQUOPY_PYTHON_VERSION=3.10", "-DCHAQUOPY_PY_SUFFIX=.so",
        f"-DCHAQUOPY_INCLUDE_PYTHON={prefix}/include", f"-DCHAQUOPY_LIB_DIRS={prefix}/lib")
    run(str(cmake), "--build", str(native), "--parallel", "2")
    return native


def package_runtime(target, bridge, output, abi, lock):
    native = {}
    with ZipFile(target) as source:
        for name in source.namelist():
            if name.startswith("jniLibs/") and name.endswith(".so"):
                native[name.replace("jniLibs/", "jni/", 1)] = source.read(name)
            elif name.startswith("lib-dynload/") and name.endswith(".so"):
                native["dynload/" + name.rsplit("/", 1)[1]] = source.read(name)
    native[f"jni/{abi}/libchaquopy_java.so"] = (bridge / "libchaquopy_java.so").read_bytes()
    native["bridge/chaquopy.so"] = (bridge / "chaquopy.so").read_bytes()
    libraries = [verify_library(name, data, abi) for name, data in native.items()]
    archive = output / f"python-native-{abi}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as result:
        for name, data in native.items():
            result.writestr(name, data)
    report = {"abi": abi, "inputs": lock, "file": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "libraries": libraries}
    (output / f"runtime-provenance-{abi}.json").write_text(json.dumps(report, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--abi", required=True, choices=["arm64-v8a", "armeabi-v7a"])
    parser.add_argument("--chaquopy", required=True, type=Path)
    parser.add_argument("--source-deps", required=True, type=Path)
    args = parser.parse_args()
    lock = json.loads((DIRECTORY / "runtime-sources.json").read_text())
    sdk, deps = args.chaquopy.resolve(), args.source_deps.resolve()
    verify_checkout(sdk, lock["chaquopy"])
    verify_checkout(deps, lock["sourceDeps"])
    configure_linker(sdk / "target/android-env.sh", lock["ndk"])
    configure_linker(deps / "android-env.sh", lock["ndk"])
    os.environ["ANDROID_API_LEVEL"] = "24"
    work = DIRECTORY / "build/runtime"
    cache = work / "source-deps"
    host = "aarch64-linux-android" if args.abi == "arm64-v8a" else "arm-linux-androideabi"
    build_dependencies(deps, lock, host, cache)
    os.environ["TV_PYTHON_SOURCE_DEPS"] = cache.resolve().as_uri()
    script = sdk / "target/python/build.sh"
    original = script.read_text()
    before = 'url_prefix="https://github.com/beeware/cpython-android-source-deps/releases/download"'
    if original.count(before) != 1:
        raise ValueError("Unexpected CPython dependency source configuration")
    script.write_text(original.replace(before, 'url_prefix="${TV_PYTHON_SOURCE_DEPS:?}"'))
    python = lock["sources"]["python"]
    download(python["url"], sdk / "target/python/build" / python["version"] / python["file"], python["sha256"])
    prefix = sdk / "target/prefix" / args.abi
    run("bash", str(script), str(prefix), python["version"], cwd=sdk)
    bridge = compile_bridge(sdk, prefix, work, args.abi)
    maven = work / "maven" / (python["version"] + "-1")
    run("bash", str(sdk / "target/package-target.sh"), str(maven), str(prefix), cwd=sdk)
    target = maven / f"target-{python['version']}-1-{args.abi}.zip"
    output = DIRECTORY / "build/runtime-output"
    output.mkdir(parents=True, exist_ok=True)
    package_runtime(target, bridge, output, args.abi, lock)


if __name__ == "__main__":
    main()
