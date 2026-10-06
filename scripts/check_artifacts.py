"""校验 canonical-only 发布制品、manifest、归档安全与校验和。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import stat
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from immich_cn.artifact_spec import (
    CHECKSUMS_FILE,
    DATASET_FILE,
    DATASET_MEMBER,
    I18N_FILE,
    MANIFEST_FILE,
    PATTERNS_FILE,
    validate_artifact_id,
    validate_canonical_filename,
)

GEO_COLUMNS = 19
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024**3
MAX_ENTRY_UNCOMPRESSED_BYTES = 1024**3
MAX_COMPRESSION_RATIO = 200


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_manifest(dist: Path, errors: list[str]) -> None:
    manifest_path = dist / MANIFEST_FILE
    if not manifest_path.exists():
        errors.append(f"缺少 {MANIFEST_FILE}")
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"{MANIFEST_FILE} 无法解析：{error}")
        return
    if manifest.get("artifactSpecVersion") != 4:
        errors.append(f"{MANIFEST_FILE} 的 artifactSpecVersion 不是 4")

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        errors.append(f"{MANIFEST_FILE} 没有 canonical artifacts")
        return
    artifact_ids: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append(f"{MANIFEST_FILE} 的 artifacts 含非对象条目")
            continue
        artifact_id = str(artifact.get("id", ""))
        canonical_file = str(artifact.get("canonicalFile", ""))
        profile = str(artifact.get("profile", ""))
        if not validate_artifact_id(artifact_id):
            errors.append(f"{MANIFEST_FILE} 含非法 artifact ID：{artifact_id!r}")
        if not validate_canonical_filename(canonical_file):
            errors.append(f"{MANIFEST_FILE} 含非法 canonical 文件名：{canonical_file!r}")
        if "{" in profile or "}" in profile or "_" in profile:
            errors.append(f"{MANIFEST_FILE} 的 profile 不稳定：{profile!r}")
        if artifact_id in artifact_ids:
            errors.append(f"{MANIFEST_FILE} 的 artifact ID 重复：{artifact_id}")
        artifact_ids.add(artifact_id)
        name = str(artifact.get("file", ""))
        if name != canonical_file:
            errors.append(f"{MANIFEST_FILE} 的 file 与 canonicalFile 不一致：{name!r} != {canonical_file!r}")
        _check_file_entry(dist, artifact, errors)

    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append(f"{MANIFEST_FILE} 没有 assets 清单")
    else:
        asset_names: set[str] = set()
        for asset in assets:
            if not isinstance(asset, dict):
                errors.append(f"{MANIFEST_FILE} 的 assets 含非对象条目")
                continue
            name = str(asset.get("file", ""))
            if name in asset_names:
                errors.append(f"{MANIFEST_FILE} 的 asset 重复：{name}")
            asset_names.add(name)
            _check_file_entry(dist, asset, errors)

    if manifest.get("patternsTable") != PATTERNS_FILE:
        errors.append(f"{MANIFEST_FILE} 的 patternsTable 不是 {PATTERNS_FILE}")
    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("file") != DATASET_FILE:
        errors.append(f"{MANIFEST_FILE} 的 dataset.file 不是 {DATASET_FILE}")


def _check_file_entry(dist: Path, entry: dict[str, object], errors: list[str]) -> None:
    name = str(entry.get("file", ""))
    path = dist / name
    if not path.exists():
        errors.append(f"manifest 列出但文件不存在：{name}")
        return
    if path.stat().st_size != int(entry.get("sizeBytes", -1)):
        errors.append(f"{name} 大小与 manifest 不一致")
    if sha256_file(path) != entry.get("sha256"):
        errors.append(f"{name} SHA256 与 manifest 不一致")


def check_zips(dist: Path, errors: list[str]) -> int:
    checked = 0
    paths = [*sorted(dist.glob("immich-cn-geodata-*.zip")), dist / I18N_FILE]
    for path in paths:
        if not path.exists():
            continue
        try:
            archive = zipfile.ZipFile(path)
        except (zipfile.BadZipFile, OSError) as error:
            errors.append(f"{path.name} 无法作为 zip 读取：{error}")
            continue
        with archive:
            bad = archive.testzip()
            if bad is not None:
                errors.append(f"{path.name} 内 {bad} 校验失败")
            check_zip_members(path, archive, errors)
            check_zip_budget(path, archive, errors)
            if path.name == I18N_FILE:
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
            notice = "geodata/NOTICE.txt"
            if notice not in archive.namelist():
                errors.append(f"{path.name} 缺少 {notice}")
            else:
                notice_text = archive.read(notice).decode("utf-8", errors="replace")
                if "GeoNames" not in notice_text or "CC BY 4.0" not in notice_text:
                    errors.append(f"{path.name} 的 {notice} 缺少 GeoNames CC BY 4.0 署名")
            with archive.open(entry) as handle:
                first = handle.readline().decode("utf-8", errors="replace")
            if len(first.rstrip("\n").split("\t")) < GEO_COLUMNS:
                errors.append(f"{path.name} 的 {entry} 首行列数不足")
            checked += 1
    return checked


def check_dataset(dist: Path, errors: list[str]) -> None:
    """校验 canonical 数据集归档、SQLite 结构和来源署名。"""
    path = dist / DATASET_FILE
    if not path.exists():
        errors.append(f"缺少约定制品：{DATASET_FILE}")
        return
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        errors.append(f"{path.name} 无法作为 zip 读取：{error}")
        return
    with archive:
        bad = archive.testzip()
        if bad is not None:
            errors.append(f"{path.name} 内 {bad} 校验失败")
        check_zip_members(path, archive, errors)
        check_zip_budget(path, archive, errors)
        required = {DATASET_MEMBER, "schema.json", "NOTICE.txt", "README.txt"}
        missing = sorted(required - set(archive.namelist()))
        if missing:
            errors.append(f"{path.name} 缺少成员：{', '.join(missing)}")
            return
        try:
            schema = json.loads(archive.read("schema.json").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"{path.name} 的 schema.json 无法解析：{error}")
            return
        if schema.get("format") != "immich-cn.dataset/1" or schema.get("schemaVersion") != 1:
            errors.append(f"{path.name} 的规范格式版本不是 immich-cn.dataset/1")
        notice = archive.read("NOTICE.txt").decode("utf-8", errors="replace")
        if "GeoNames" not in notice or "CC BY 4.0" not in notice:
            errors.append(f"{path.name} 的 NOTICE.txt 缺少 GeoNames CC BY 4.0 署名")

        with tempfile.TemporaryDirectory(prefix="immich-cn-dataset-") as temporary:
            sqlite_path = Path(temporary) / DATASET_MEMBER
            with archive.open(DATASET_MEMBER) as source, sqlite_path.open("wb") as target:
                shutil.copyfileobj(source, target)
            try:
                connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
            except sqlite3.Error as error:
                errors.append(f"{path.name} 的 {DATASET_MEMBER} 无法打开：{error}")
                return
            try:
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
                }
                required_tables = {
                    "dataset_meta",
                    "sources",
                    "countries",
                    "admin_areas",
                    "places",
                    "place_names",
                }
                if missing_tables := sorted(required_tables - tables):
                    errors.append(f"{path.name} 的 SQLite 缺少表：{', '.join(missing_tables)}")
                    return
                place_count = connection.execute("SELECT COUNT(*) FROM places").fetchone()[0]
                name_count = connection.execute("SELECT COUNT(*) FROM place_names").fetchone()[0]
                meta = dict(connection.execute("SELECT key, value FROM dataset_meta").fetchall())
                if place_count < 1:
                    errors.append(f"{path.name} 的 places 表为空")
                if name_count != place_count:
                    errors.append(f"{path.name} 的 places/place_names 数量不一致：{place_count}/{name_count}")
                if meta.get("schemaVersion") != "1" or meta.get("format") != "immich-cn.dataset/1":
                    errors.append(f"{path.name} 的 dataset_meta 格式版本不一致")
            except sqlite3.Error as error:
                errors.append(f"{path.name} 的 SQLite 结构无法校验：{error}")
            finally:
                connection.close()


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


def check_zip_budget(path: Path, archive: zipfile.ZipFile, errors: list[str]) -> None:
    """限制单成员/整包解压总量与压缩比，避免制品成为 zip 炸弹。"""
    total = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        total += info.file_size
        if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 解压后超过 {MAX_ENTRY_UNCOMPRESSED_BYTES} 字节")
        ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size and ratio > MAX_COMPRESSION_RATIO:
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 压缩比 {ratio:.1f} 超过 {MAX_COMPRESSION_RATIO}")
    if total > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        errors.append(f"{path.name} 解压总量 {total} 超过 {MAX_ARCHIVE_UNCOMPRESSED_BYTES} 字节")


def check_checksums(dist: Path, errors: list[str]) -> int:
    path = dist / CHECKSUMS_FILE
    if not path.exists():
        errors.append(f"缺少 {CHECKSUMS_FILE}")
        return 0
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        errors.append(f"{CHECKSUMS_FILE} 为空")
        return 0
    verified = 0
    for line in lines:
        digest, _, name = line.partition("  ")
        target = dist / name
        if not target.exists():
            errors.append(f"{CHECKSUMS_FILE} 列出的文件不存在：{name}")
            continue
        if sha256_file(target) != digest:
            errors.append(f"{CHECKSUMS_FILE} 与实际文件不符：{name}")
        verified += 1
    return verified


def check_dist_entries(dist: Path, errors: list[str]) -> None:
    """dist 只应包含本次构建登记的制品。

    发布路径是 `gh release upload ... dist/*` / `gh release create ... dist/*`，
    因此任何残留文件都会被一起上传；历史命名或临时文件不能被静默放过。
    """
    manifest_path = dist / MANIFEST_FILE
    if not manifest_path.is_file():
        return  # 缺少 manifest 已由 check_required_files 报出
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        errors.append(f"{MANIFEST_FILE} 不是合法 JSON：{error}")
        return
    if not isinstance(manifest, dict):
        errors.append(f"{MANIFEST_FILE} 顶层不是对象")
        return

    allowed = {MANIFEST_FILE, CHECKSUMS_FILE}
    for key in ("artifacts", "assets"):
        for entry in manifest.get(key) or []:
            if isinstance(entry, dict) and isinstance(entry.get("file"), str):
                allowed.add(entry["file"])
    unexpected = sorted(path.name for path in dist.iterdir() if path.name not in allowed)
    if unexpected:
        errors.append(
            "dist 含未登记的残留文件（发布会用 dist/* 一起上传）："
            + "、".join(unexpected)
            + "；请清理后重跑，或用 `immich-cn all --clean`"
        )


def check_required_files(dist: Path, errors: list[str]) -> None:
    required = (
        "immich-cn-geodata-admin2-default-v1.zip",
        "immich-cn-geodata-admin2-full-v1.zip",
        DATASET_FILE,
        PATTERNS_FILE,
        I18N_FILE,
        MANIFEST_FILE,
        CHECKSUMS_FILE,
    )
    for name in required:
        if not (dist / name).exists():
            errors.append(f"缺少约定制品：{name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args(argv)

    errors: list[str] = []
    check_required_files(args.dist, errors)
    check_manifest(args.dist, errors)
    check_dist_entries(args.dist, errors)
    zips = check_zips(args.dist, errors)
    check_dataset(args.dist, errors)
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
