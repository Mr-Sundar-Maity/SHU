"""Generate a CSV inventory of license metadata in SHU's active Python env."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from importlib import metadata
from pathlib import Path


_LICENSE_FILE = re.compile(r"(?i)(license|licence|copying|notice)")


def _fields(distribution: metadata.Distribution) -> tuple[str, str, str]:
    package_metadata = distribution.metadata
    expression = package_metadata.get("License-Expression", "").strip()
    legacy = package_metadata.get("License", "").strip()
    classifiers = sorted(
        classifier.split("::", 1)[1].strip()
        for classifier in package_metadata.get_all("Classifier", [])
        if classifier.startswith("License ::")
    )
    license_files = sorted(
        str(path)
        for path in (distribution.files or [])
        if _LICENSE_FILE.search(path.name)
    )
    return (
        expression or legacy or "",
        "; ".join(classifiers),
        "; ".join(license_files),
    )


def generate(output: Path) -> tuple[int, int]:
    if sys.prefix == sys.base_prefix:
        raise RuntimeError("Run this script from SHU's virtual environment")
    project_root = Path(__file__).resolve().parents[1]
    destination = output.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    missing_metadata = 0
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name") or "unknown"
        version = distribution.version
        declared, classifiers, license_files = _fields(distribution)
        if not declared and not classifiers and not license_files:
            missing_metadata += 1
        rows.append(
            {
                "package": name,
                "version": version,
                "license_expression_or_text": declared,
                "license_classifiers": classifiers,
                "license_files_in_distribution": license_files,
            }
        )
    rows.sort(key=lambda row: (row["package"].casefold(), row["version"]))
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else [
            "package", "version", "license_expression_or_text",
            "license_classifiers", "license_files_in_distribution",
        ])
        writer.writeheader()
        writer.writerows(rows)
    try:
        destination.relative_to(project_root)
        display_path = destination.relative_to(project_root)
    except ValueError:
        display_path = destination
    print(f"Inventoried {len(rows)} installed distributions: {display_path}")
    print(f"Distributions with no license metadata or license files: {missing_metadata}")
    print("Metadata is a review aid, not a legal determination; inspect each license before release.")
    return len(rows), missing_metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "THIRD_PARTY_LICENSES.csv",
    )
    args = parser.parse_args()
    try:
        generate(args.output)
    except Exception as error:
        print(f"License inventory failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
