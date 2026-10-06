"""校验发布制品：manifest 与实际文件一致、zip 可解、cities500 结构正确、校验和匹配。

CI 中此前只校验 geodata 目录，从未验证过真正对外发布的 zip，
因此制品损坏或 manifest 与实际文件不一致时会"静默通过"。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

GEO_COLUMNS = 19


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_manifest(dist: Path, errors: list[str]) -> None:
    manifest_path = dist / "manifest.json"
    if not manifest_path.exists():
        errors.append("缺少 manifest.json")
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    variants = manifest.get("variants")
    if not isinstance(variants, list) or not variants:
        errors.append("manifest.json 没有 variants")
        return

    for variant in variants:
        name = str(variant.get("file", ""))
        path = dist / name
        if not path.exists():
            errors.append(f"manifest 列出但文件不存在：{name}")
            continue
        if path.stat().st_size != int(variant.get("sizeBytes", -1)):
            errors.append(f"{name} 大小与 manifest 不一致")
        if sha256_file(path) != variant.get("sha256"):
            errors.append(f"{name} SHA256 与 manifest 不一致")


def check_zips(dist: Path, errors: list[str]) -> int:
    checked = 0
    for path in sorted(dist.glob("geodata*.zip")) + sorted(dist.glob("i18n-iso-countries.zip")):
        try:
            archive = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as error:
            # 损坏的 zip 必须以可读的校验错误呈现，而不是抛栈崩掉整个检查
            errors.append(f"{path.name} 无法作为 zip 读取：{error}")
            continue
        with archive:
            bad = archive.testzip()
            if bad is not None:
                errors.append(f"{path.name} 内 {bad} 校验失败")
            check_zip_members(path, archive, errors)
            if path.name == "i18n-iso-countries.zip":
                try:
                    license_text = archive.read("LICENSE").decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    errors.append(f"{path.name} 缺少可读的 LICENSE")
                else:
                    if "MIT License" not in license_text or "Copyright" not in license_text:
                        errors.append(f"{path.name} 的 LICENSE 不是完整的 MIT 版权声明")
                checked += 1
                continue
            entry = "geodata/cities500.txt"
            if entry not in archive.namelist():
                errors.append(f"{path.name} 缺少 {entry}")
                continue
            with archive.open(entry) as handle:
                first = handle.readline().decode("utf-8", errors="replace")
            if len(first.rstrip("\n").split("\t")) < GEO_COLUMNS:
                errors.append(f"{path.name} 的 {entry} 首行列数不足")
            checked += 1
    return checked


def check_zip_members(path: Path, archive: zipfile.ZipFile, errors: list[str]) -> None:
    """拒绝可能造成 Zip Slip 或符号链接逃逸的归档成员。"""
    for info in archive.infolist():
        raw = info.filename.replace("\\", "/")
        member = PurePosixPath(raw)
        if raw.startswith("/") or member.is_absolute() or ".." in member.parts:
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 路径越界")
            continue
        if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 使用绝对路径")
            continue
        if stat.S_ISLNK(info.external_attr >> 16):
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 是符号链接")


def check_checksums(dist: Path, errors: list[str]) -> int:
    path = dist / "SHA256SUMS"
    if not path.exists():
        errors.append("缺少 SHA256SUMS")
        return 0
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        errors.append("SHA256SUMS 为空")
        return 0
    verified = 0
    for line in lines:
        digest, _, name = line.partition("  ")
        target = dist / name
        if not target.exists():
            errors.append(f"SHA256SUMS 列出的文件不存在：{name}")
            continue
        actual = sha256_file(target)
        if actual != digest:
            errors.append(f"SHA256SUMS 与实际文件不符：{name}")
        verified += 1
    return verified


def check_required_files(dist: Path, errors: list[str]) -> None:
    for name in ("geodata.zip", "geodata_full.zip", "patterns.tsv.gz"):
        if not (dist / name).exists():
            errors.append(f"缺少约定制品：{name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)

    errors: list[str] = []
    check_required_files(args.dist, errors)
    check_manifest(args.dist, errors)
    zips = check_zips(args.dist, errors)
    verified = check_checksums(args.dist, errors)

    for error in errors:
        print(f"[!!] {error}")
    if errors:
        print(f"制品校验失败：{len(errors)} 项")
        return 1
    print(f"制品校验通过：{zips} 个压缩包、{verified} 项校验和")
    return 0


if __name__ == "__main__":
    sys.exit(main())
