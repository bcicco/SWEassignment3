# builds the Lambda deployment zip: src/swe plus its dependencies, built for Lambda's
# Linux arm64 runtime (pydantic has compiled parts, so Mac wheels won't load)
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUILD = ROOT / "build" / "lambda"
ZIP_PATH = ROOT / "build" / "lambda.zip"
RUNTIME_PYTHON = "3.11"

# the Lambda runtime already ships these, and they're most of the bundle's size
PROVIDED_BY_RUNTIME = ["boto3", "botocore", "s3transfer"]


def build() -> bytes:
    shutil.rmtree(BUILD, ignore_errors = True)
    BUILD.mkdir(parents = True)
    requirements = BUILD.parent / "requirements.txt"
    subprocess.run(
        ["uv", "export", "--no-dev", "--no-hashes", "--no-emit-project", "--quiet", "-o", str(requirements)]
        + [arg for pkg in PROVIDED_BY_RUNTIME for arg in ("--no-emit-package", pkg)],
        cwd = ROOT, check = True,
    )
    subprocess.run(
        ["uv", "pip", "install", "--quiet", "-r", str(requirements), "--target", str(BUILD),
         "--python-platform", "aarch64-manylinux2014", "--python-version", RUNTIME_PYTHON, "--only-binary", ":all:"],
        cwd = ROOT, check = True,
    )
    shutil.copytree(ROOT / "src" / "swe", BUILD / "swe", ignore = shutil.ignore_patterns("__pycache__"))

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                zf.write(path, path.relative_to(BUILD))
    return ZIP_PATH.read_bytes()


if __name__ == "__main__":
    size = len(build())
    print(f"built {ZIP_PATH.relative_to(ROOT)} ({size / 1_000_000:.1f} MB)")
