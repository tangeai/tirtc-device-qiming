"""Restore the exact P4 build assets from a locally authorized directory."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil


ROOT = Path(__file__).resolve().parents[1]


def confined(root, name):
    rel = PurePosixPath(name)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"invalid manifest path: {name}")
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path is outside the input directory: {name}")
    return path


def matches(path, entry):
    if not path.is_file() or path.stat().st_size != entry["bytes"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest() == entry["sha256"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--check", action="store_true", help="verify the project files without writing")
    args = parser.parse_args()
    if args.check == (args.directory is not None):
        parser.error("supply either --check or one input directory")
    if args.directory is not None and not args.directory.is_dir():
        parser.error("input directory does not exist")

    manifest = json.loads((ROOT / "external-assets.json").read_text(encoding="utf-8"))["files"]
    copies = []
    problems = []
    for name, entry in manifest.items():
        dest = confined(ROOT, name)
        if matches(dest, entry):
            continue
        if args.check or dest.exists():
            problems.append(name)
            continue
        origin = confined(args.directory.resolve(), name)
        if not matches(origin, entry):
            problems.append(name)
        else:
            copies.append((origin, dest, entry))

    if problems:
        for name in problems:
            print(f"Missing or mismatched: {name}")
        parser.exit(1, f"{len(problems)} input(s) failed verification; no files written.\n")

    for origin, dest, entry in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with origin.open("rb") as source, dest.open("xb") as target:
            shutil.copyfileobj(source, target)
        if not matches(dest, entry):
            parser.exit(1, f"Verification failed after copying: {dest.relative_to(ROOT)}\n")
    print(f"{len(manifest)} external build inputs verified.")


if __name__ == "__main__":
    main()
