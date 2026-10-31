import argparse
from email.parser import Parser
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from zipfile import ZipFile


DIRECTORY = Path(__file__).resolve().parent
MANIFEST = "pure-wheels-manifest.json"


def read_inputs():
    return json.loads((DIRECTORY / "pure-sources.json").read_text(encoding="utf-8"))


def download_source(package, directory):
    archive = directory / package["url"].rsplit("/", 1)[1]
    urllib.request.urlretrieve(package["url"], archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != package["sha256"]:
        raise ValueError("Pure Python source hash mismatch")
    return archive


def source_files(archive, package):
    prefix = f"{package['name']}-{package['version']}/"
    with tarfile.open(archive) as source:
        return {member.name.removeprefix(prefix): source.extractfile(member).read() for member in source.getmembers() if member.isfile() and member.name.startswith(prefix + package["name"] + "/") and member.name.endswith(".py")}


def verify_wheel(path, package, sources):
    expected = f"{package['name']}-{package['version']}-py3-none-any.whl"
    if path.name != expected or not sources:
        raise ValueError("Unexpected pure Python wheel")
    metadata = f"{package['name']}-{package['version']}.dist-info/"
    with ZipFile(path) as wheel:
        names = wheel.namelist()
        if wheel.testzip() is not None or len(names) != len(set(names)):
            raise ValueError("Invalid pure Python wheel")
        info = Parser().parsestr(wheel.read(metadata + "WHEEL").decode())
        if info["Root-Is-Purelib"] != "true" or info.get_all("Tag") != ["py3-none-any"]:
            raise ValueError("Wheel is not platform independent")
        info = Parser().parsestr(wheel.read(metadata + "METADATA").decode())
        if info["Name"] != package["name"] or info["Version"] != package["version"]:
            raise ValueError("Pure Python package metadata mismatch")
        if info.get_all("Requires-Dist") != ["numpy"]:
            raise ValueError("Pure Python dependency metadata mismatch")
        files = {name: wheel.read(name) for name in names if not name.startswith(metadata)}
        if files != sources:
            raise ValueError("Pure Python wheel differs from the official source")
    return {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size, "sourceFiles": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(sources.items())}}


def verify_artifacts(directory):
    inputs = read_inputs()
    report = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    if report["inputs"] != inputs or len(report["wheels"]) != 1:
        raise ValueError("Unexpected pure Python build inputs")
    with tempfile.TemporaryDirectory(prefix="pywasm-verify-") as temporary:
        archive = download_source(inputs["package"], Path(temporary))
        sources = source_files(archive, inputs["package"])
        wheel = report["wheels"][0]
        path = directory / wheel["file"]
        if path.name != wheel["file"] or verify_wheel(path, inputs["package"], sources) != wheel:
            raise ValueError("Pure Python wheel provenance mismatch")
    return report


def build(output):
    inputs = read_inputs()
    for name, version in inputs["buildRequirements"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError(f"Unexpected build tool version: {name}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pywasm-build-", dir=output.parent) as temporary:
        work = Path(temporary)
        archive = download_source(inputs["package"], work)
        environment = dict(os.environ, SOURCE_DATE_EPOCH="315532800")
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-cache-dir", "--wheel-dir", str(work / "wheels"), str(archive)], env=environment, check=True)
        wheels = list((work / "wheels").glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected one pure Python wheel")
        report = {"inputs": inputs, "wheels": [verify_wheel(wheels[0], inputs["package"], source_files(archive, inputs["package"]))]}
        shutil.copyfile(wheels[0], output / wheels[0].name)
        (output / MANIFEST).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
