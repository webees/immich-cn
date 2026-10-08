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
from immich_cn.localization import SPECIAL_ADMIN_TOP_LEVEL

GEO_COLUMNS = 19
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 2 * 1024**3
MAX_ENTRY_UNCOMPRESSED_BYTES = 1024**3
MAX_COMPRESSION_RATIO = 200

#: 同一次校验里，每个制品会被 manifest.artifacts、manifest.assets 与 checksums 各引用一次。
#: 真实 dist（615 MB）因此被重复读取约 2.9 遍（合计 1.77 GB）。按
#: 「路径 + mtime + ctime + 大小」缓存摘要，文件在校验期间被改动时缓存自动失效，
#: 即使调用方把 mtime 恢复成原值也不能复用旧摘要。
_DIGEST_CACHE: dict[tuple[Path, int, int, int], str] = {}


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def sha256_file(path: Path) -> str:
    stat_result = path.stat()
    key = (path, stat_result.st_mtime_ns, stat_result.st_ctime_ns, stat_result.st_size)
    cached = _DIGEST_CACHE.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _DIGEST_CACHE[key] = value
    return value


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
    artifact_files: set[str] = set()
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
        artifact_files.add(name)
        if name != canonical_file:
            errors.append(f"{MANIFEST_FILE} 的 file 与 canonicalFile 不一致：{name!r} != {canonical_file!r}")
        _check_file_entry(dist, artifact, errors)

    assets = manifest.get("assets")
    asset_files: set[str] = set()
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
            asset_files.add(name)
            _check_file_entry(dist, asset, errors)
    missing_assets = sorted(artifact_files - asset_files)
    if missing_assets:
        errors.append(f"{MANIFEST_FILE} 的 artifacts 未出现在 assets：" + "、".join(missing_assets))

    if manifest.get("patternsTable") != PATTERNS_FILE:
        errors.append(f"{MANIFEST_FILE} 的 patternsTable 不是 {PATTERNS_FILE}")
    dataset = manifest.get("dataset")
    if not isinstance(dataset, dict) or dataset.get("file") != DATASET_FILE:
        errors.append(f"{MANIFEST_FILE} 的 dataset.file 不是 {DATASET_FILE}")


def _check_file_entry(dist: Path, entry: dict[str, object], errors: list[str]) -> None:
    name = str(entry.get("file", ""))
    path = dist / name
    if not path.is_file():
        errors.append(f"manifest 列出但文件不存在或不是普通文件：{name}")
        return
    size_bytes = entry.get("sizeBytes")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
        errors.append(f"{name} 的 sizeBytes 不是整数")
    elif path.stat().st_size != size_bytes:
        errors.append(f"{name} 大小与 manifest 不一致")
    digest = entry.get("sha256")
    if not _is_sha256(digest):
        errors.append(f"{name} 的 sha256 不是 64 位十六进制摘要")
    elif sha256_file(path) != digest:
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
                # 语言包必须被裁剪过：旧版 Immich 只读 langs/en.json，把整套语言包塞进
                # 制品会白白放大体积（2026-10-06 的发布里曾含 73 个语言文件）。
                members = set(archive.namelist())
                if "langs/en.json" not in members:
                    errors.append(f"{path.name} 缺少 langs/en.json")
                extra_langs = sorted(name for name in members if name.startswith("langs/") and name != "langs/en.json")
                if extra_langs:
                    errors.append(
                        f"{path.name} 含 {len(extra_langs)} 个非必需语言文件（如 {extra_langs[0]}），"
                        "应只保留 langs/en.json"
                    )
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
                # 只查 places/place_names 不够：countries 为空会让 localized_places 的国家名全为 NULL。
                # 不查 sources——`--skip-fetch` 路径本来就不产生 SourceRecord，合成冒烟构建依赖它。
                counts = {
                    "countries": connection.execute("SELECT COUNT(*) FROM countries").fetchone()[0],
                    "admin_areas": connection.execute("SELECT COUNT(*) FROM admin_areas").fetchone()[0],
                }
                for label, count in counts.items():
                    if count < 1:
                        errors.append(f"{path.name} 的 {label} 表为空")
            except sqlite3.Error as error:
                errors.append(f"{path.name} 的 SQLite 结构无法校验：{error}")
            finally:
                connection.close()


def _dataset_admin_areas(dataset: Path) -> dict[tuple[int, str], str]:
    """读出规范数据集里 ``admin_areas`` 的 ``(level, code) -> name``。"""
    with zipfile.ZipFile(dataset) as archive, tempfile.TemporaryDirectory(prefix="immich-cn-admin-") as temporary:
        sqlite_path = Path(temporary) / DATASET_MEMBER
        with archive.open(DATASET_MEMBER) as source, sqlite_path.open("wb") as target:
            shutil.copyfileobj(source, target)
        connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
        try:
            return {
                (int(level), str(code)): str(name)
                for level, code, name in connection.execute("SELECT level, code, name FROM admin_areas")
            }
        finally:
            connection.close()


def _adapter_admin_names(geodata: Path) -> dict[tuple[int, str], str]:
    """读出 Immich 适配器里 admin1/admin2 表的 ``(level, code) -> name``。"""
    names: dict[tuple[int, str], str] = {}
    with zipfile.ZipFile(geodata) as archive:
        for member, level in (("geodata/admin1CodesASCII.txt", 1), ("geodata/admin2Codes.txt", 2)):
            for line in archive.read(member).decode("utf-8").splitlines():
                fields = line.split("\t")
                if len(fields) >= 2 and fields[0]:
                    names[(level, fields[0])] = fields[1]
    return names


def check_admin_area_consistency(dist: Path, errors: list[str]) -> None:
    """规范数据集与 Immich 适配器必须给出同一份行政层级名称。

    两者由同一次构建产出，规范数据集是事实源。唯一的例外是 HK/MO 的 level-1：GeoNames
    把区/堂区当作 admin1，而 Immich 会把 admin1Name 当"省/州"展示，因此适配器按
    ``SPECIAL_ADMIN_TOP_LEVEL`` 刻意改写成特别行政区名称。除此之外的任何差异都说明
    两份制品已经不来自同一次构建，必须失败而不是任其漂移。
    """
    dataset = dist / DATASET_FILE
    candidates = sorted(dist.glob("immich-cn-geodata-*-default-v1.zip"))
    if not dataset.exists() or not candidates:
        return  # 缺件由 check_required_files / check_dataset 负责报错
    geodata = candidates[0]
    try:
        dataset_admin = _dataset_admin_areas(dataset)
        adapter_admin = _adapter_admin_names(geodata)
    except (zipfile.BadZipFile, OSError, sqlite3.Error, UnicodeDecodeError, KeyError) as error:
        errors.append(f"无法比对 admin 层级一致性（{geodata.name} vs {DATASET_FILE}）：{error}")
        return
    if not dataset_admin or not adapter_admin:
        errors.append("admin 层级一致性检查没有可比较的数据，护栏可能已失效")
        return

    mismatches: list[str] = []
    for (level, code), adapter_name in sorted(adapter_admin.items()):
        dataset_name = dataset_admin.get((level, code))
        if dataset_name is None or dataset_name == adapter_name:
            continue
        country = code.split(".")[0]
        override = SPECIAL_ADMIN_TOP_LEVEL.get(country)
        if level == 1 and override is not None and adapter_name == override:
            continue
        mismatches.append(f"{code}: dataset={dataset_name!r} adapter={adapter_name!r}")
    if mismatches:
        errors.append(
            f"规范数据集与 Immich 适配器的 admin 名称有 {len(mismatches)} 处未记录差异："
            + "；".join(mismatches[:5])
            + "（只允许 HK/MO 的 level-1 显式覆盖）"
        )

    for country, expected in sorted(SPECIAL_ADMIN_TOP_LEVEL.items()):
        codes = [code for level, code in adapter_admin if level == 1 and code.startswith(f"{country}.")]
        if not codes:
            continue
        wrong = [code for code in codes if adapter_admin[(1, code)] != expected]
        if wrong:
            errors.append(f"{country} 的 admin1 特别行政区覆盖未生效：{wrong[:3]} 的名称不是 {expected!r}")


def check_admin_code_resolution(dist: Path, errors: list[str]) -> None:
    """适配器自己的 cities500.txt 引用的行政代码必须能在同一份制品的 adminN 表里解析。

    Immich 用 ``${country}.${admin1}``（admin1Name）与 ``${country}.${admin1}.${admin2}``
    （admin2Name）做键；缺条目的行会写入 ``null``，按该行政区名检索就会落空。
    """
    candidates = sorted(dist.glob("immich-cn-geodata-*-default-v1.zip"))
    if not candidates:
        return  # 缺件由 check_required_files / check_zips 负责报错
    geodata = candidates[0]
    unresolved1: dict[str, int] = {}
    unresolved2: dict[str, int] = {}
    try:
        names = _adapter_admin_names(geodata)
        with zipfile.ZipFile(geodata) as archive, archive.open("geodata/cities500.txt") as handle:
            for raw_line in handle:
                fields = raw_line.decode("utf-8").rstrip("\n").split("\t")
                if len(fields) < 19:
                    continue
                country, admin1, admin2 = fields[8], fields[10], fields[11]
                if admin1 and (1, f"{country}.{admin1}") not in names:
                    key = f"{country}.{admin1}"
                    unresolved1[key] = unresolved1.get(key, 0) + 1
                if admin2 and (2, f"{country}.{admin1}.{admin2}") not in names:
                    key = f"{country}.{admin1}.{admin2}"
                    unresolved2[key] = unresolved2.get(key, 0) + 1
    except (zipfile.BadZipFile, OSError, UnicodeDecodeError, KeyError) as error:
        errors.append(f"无法校验行政代码可解析性（{geodata.name}）：{error}")
        return
    if unresolved1 or unresolved2:
        samples = "、".join(sorted(unresolved1)[:3] + sorted(unresolved2)[:3])
        errors.append(
            f"{geodata.name} 有 {len(unresolved1) + len(unresolved2)} 个行政代码无法解析"
            f"（admin1 {sum(unresolved1.values())} 行、admin2 {sum(unresolved2.values())} 行）：{samples}"
        )


def check_zip_members(path: Path, archive: zipfile.ZipFile, errors: list[str]) -> None:
    """拒绝可能造成 Zip Slip 或符号链接逃逸的归档成员。"""
    seen: dict[str, int] = {}
    for info in archive.infolist():
        raw = info.filename.replace("\\", "/")
        seen[raw] = seen.get(raw, 0) + 1
        member = PurePosixPath(raw)
        if raw.startswith("/") or member.is_absolute() or ".." in member.parts:
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 路径越界")
            continue
        if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 使用绝对路径")
            continue
        if stat.S_ISLNK(info.external_attr >> 16):
            errors.append(f"{path.name} 的归档成员 {info.filename!r} 是符号链接")
    # 同名重复成员会让「已校验的内容」与「解压后生效的内容」不一致：
    # ZipFile.read 取最后一个，`unzip -p` 会把两个成员首尾拼接，解压则覆盖成最后一个。
    duplicates = sorted(name for name, count in seen.items() if count > 1)
    if duplicates:
        errors.append(f"{path.name} 含同名重复归档成员：" + "、".join(duplicates))


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
    names: list[str] = []
    for line in lines:
        digest, separator, name = line.partition("  ")
        if not separator or not name or not _is_sha256(digest) or "/" in name or "\\" in name or name in {".", ".."}:
            errors.append(f"{CHECKSUMS_FILE} 含格式错误的条目：{line!r}")
            continue
        names.append(name)
        target = dist / name
        if not target.is_file():
            errors.append(f"{CHECKSUMS_FILE} 列出的文件不存在：{name}")
            continue
        if sha256_file(target) != digest:
            errors.append(f"{CHECKSUMS_FILE} 与实际文件不符：{name}")
        verified += 1
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        errors.append(f"{CHECKSUMS_FILE} 含重复条目：" + "、".join(duplicates))

    manifest_path = dist / MANIFEST_FILE
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = None
        if isinstance(manifest, dict):
            expected = {MANIFEST_FILE}
            for entry in manifest.get("assets") or []:
                if isinstance(entry, dict) and isinstance(entry.get("file"), str):
                    expected.add(entry["file"])
            actual = set(names)
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            if missing:
                errors.append(f"{CHECKSUMS_FILE} 未覆盖 manifest assets：" + "、".join(missing))
            if extra:
                errors.append(f"{CHECKSUMS_FILE} 含 manifest 未登记的条目：" + "、".join(extra))
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
    check_admin_area_consistency(args.dist, errors)
    check_admin_code_resolution(args.dist, errors)
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
