"""Install explicitly named, checksum-verified tools inside ignored .tools only."""

import argparse
import hashlib
import json
import platform
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def unpack(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Archive path leaves tool directory")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("Tool archive contains an unsupported symbolic link")
            bundle.extract(entry, destination)
            if mode & 0o111 and target.is_file():
                target.chmod(0o755)


def install(name: str, spec: dict) -> None:
    if spec["platform"] not in ("any", platform.system()):
        raise ValueError(f"{name} requires {spec['platform']}")
    tools = ROOT / ".tools"
    tools.mkdir(exist_ok=True)
    target = tools / f"{name}-{spec['version']}"
    marker = target / ".archive-sha256"
    if marker.is_file() and marker.read_text().strip() == spec["sha256"]:
        print(f"Already installed: {target}", flush=True)
        return
    if target.exists():
        raise ValueError(f"Unverified existing directory: {target}; inspect it before retrying")
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=tools) as work:
        archive = Path(work) / "download"
        print(f"Downloading {name} {spec['version']}", flush=True)
        with urllib.request.urlopen(spec["url"], timeout=60) as source, archive.open("wb") as out:
            shutil.copyfileobj(source, out)
        with archive.open("rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if digest != spec["sha256"]:
            raise ValueError(f"Checksum mismatch for {name}")
        staging = Path(work) / "unpacked"
        staging.mkdir()
        if spec["format"] == "zip":
            unpack(archive, staging)
        else:
            shutil.copyfile(archive, staging / name)
            (staging / name).chmod(0o755)
        (staging / ".archive-sha256").write_text(digest + "\n")
        staging.rename(target)
    print(f"Verified and installed: {target}", flush=True)


def main() -> None:
    specifications = json.loads((ROOT / "scripts/tool-versions.json").read_text())["tools"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tools", choices=list(specifications), nargs="+")
    arguments = parser.parse_args()
    for name in arguments.tools:
        install(name, specifications[name])


if __name__ == "__main__":
    main()
