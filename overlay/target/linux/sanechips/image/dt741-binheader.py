#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 DT741 的标准 Legacy uImage 添加 0x1E0 字节厂商 binheader。"""

from __future__ import annotations

import argparse
import os
import stat
import struct
import sys
import tempfile
import zlib
from pathlib import Path


BINHEADER_SIZE = 0x1E0
UIMAGE_HEADER_SIZE = 64
VENDOR_MAGIC = bytes.fromhex("99 99 99 99 44 44 44 44 55 55 55 55 aa aa aa aa")
UIMAGE_MAGIC = 0x27051956

# DT741 厂商头中已确认的字段偏移；多字节字段均为 little-endian。
OFF_ALIGNED_END_1 = 0x54
OFF_UIMAGE_LENGTH = 0x58
OFF_BINHEADER_LENGTH = 0x5C
OFF_UIMAGE_CRC = 0x60
OFF_ALIGNED_END_2 = 0x68
OFF_HEADER_CRC = 0x110
OFF_SLOT_STATE = 0x128

SLOT_STATE = {
    "a": bytes.fromhex("ff ff ff ff"),
    "b": bytes.fromhex("00 00 00 00"),
}


def crc32(data: bytes) -> int:
    """返回与 zlib/标准 CRC32 一致的无符号 32 位值。"""
    return zlib.crc32(data) & 0xFFFFFFFF


def get_le32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def put_le32(data: bytearray, offset: int, value: int) -> None:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError(f"字段 0x{offset:x} 超出 32 位范围：0x{value:x}")
    struct.pack_into("<I", data, offset, value)


def validate_uimage(image: bytes) -> None:
    """验证输入是完整、未被破坏的 Legacy Linux Kernel uImage。"""
    if len(image) < UIMAGE_HEADER_SIZE:
        raise ValueError(
            f"uImage 长度不足 64 字节：实际 {len(image)} 字节"
        )

    magic = struct.unpack_from(">I", image, 0)[0]
    if magic != UIMAGE_MAGIC:
        raise ValueError(
            f"uImage magic 错误：读到 0x{magic:08x}，"
            f"期望 0x{UIMAGE_MAGIC:08x}"
        )

    # Legacy uImage 的头 CRC 按大端字段读取；计算时先将 hcrc 清零。
    stored_hcrc = struct.unpack_from(">I", image, 4)[0]
    header = bytearray(image[:UIMAGE_HEADER_SIZE])
    header[4:8] = b"\x00\x00\x00\x00"
    actual_hcrc = crc32(header)
    if stored_hcrc != actual_hcrc:
        raise ValueError(
            f"uImage header CRC 错误：存储 0x{stored_hcrc:08x}，"
            f"计算 0x{actual_hcrc:08x}"
        )

    payload_size = struct.unpack_from(">I", image, 12)[0]
    actual_payload_size = len(image) - UIMAGE_HEADER_SIZE
    if payload_size != actual_payload_size:
        raise ValueError(
            f"uImage payload 长度不符：头部声明 {payload_size} 字节，"
            f"文件实际 {actual_payload_size} 字节"
        )

    stored_dcrc = struct.unpack_from(">I", image, 24)[0]
    actual_dcrc = crc32(image[UIMAGE_HEADER_SIZE:])
    if stored_dcrc != actual_dcrc:
        raise ValueError(
            f"uImage data CRC 错误：存储 0x{stored_dcrc:08x}，"
            f"计算 0x{actual_dcrc:08x}"
        )

    # OpenWrt 管线使用 uImage none；这里检查 Linux / Kernel / none，
    # 不硬编码 CPU arch，避免把架构编号写死在通用封装工具中。
    os_id, _arch_id, image_type, compression = image[28:32]
    if os_id != 5:
        raise ValueError(f"uImage OS 类型不是 Linux：ih_os={os_id}")
    if image_type != 2:
        raise ValueError(f"uImage 类型不是 Kernel：ih_type={image_type}")
    if compression != 0:
        raise ValueError(
            f"uImage 不是 none 压缩：ih_comp={compression}，期望 0"
        )


def load_template(path: Path) -> bytearray:
    template = path.read_bytes()
    if len(template) != BINHEADER_SIZE:
        raise ValueError(
            f"binheader 模板必须恰好为 0x{BINHEADER_SIZE:x}（480）字节，"
            f"实际为 {len(template)} 字节：{path}"
        )

    if template[:len(VENDOR_MAGIC)] != VENDOR_MAGIC:
        raise ValueError("binheader 模板厂商魔数不匹配，拒绝使用")

    if get_le32(template, OFF_BINHEADER_LENGTH) != BINHEADER_SIZE:
        raise ValueError(
            f"模板 0x5c 字段不是 0x{BINHEADER_SIZE:x}："
            f"读到 0x{get_le32(template, OFF_BINHEADER_LENGTH):x}"
        )

    slot_state = bytes(template[OFF_SLOT_STATE:OFF_SLOT_STATE + 4])
    if slot_state not in SLOT_STATE.values():
        raise ValueError(
            "模板 0x128–0x12b 不是已知的 A/B 槽状态（FFFFFFFF/00000000）"
        )

    stored_crc = get_le32(template, OFF_HEADER_CRC)
    actual_crc = crc32(template[0x14:OFF_HEADER_CRC])
    if stored_crc != actual_crc:
        raise ValueError(
            f"模板 Header CRC 错误：存储 0x{stored_crc:08x}，"
            f"计算 0x{actual_crc:08x}"
        )

    return bytearray(template)


def make_image(uimage: bytes, template: bytearray, slot: str) -> bytes:
    validate_uimage(uimage)

    uimage_length = len(uimage)
    actual_end = BINHEADER_SIZE + uimage_length
    aligned_end = (actual_end + 15) & ~0x0F
    if uimage_length > 0xFFFFFFFF or aligned_end > 0xFFFFFFFF:
        raise ValueError("uImage 长度或对齐结束地址超出 32 位字段范围")

    # 仅改写已由 DT741 原厂样本确认的动态字段；其它模板字节全部保留。
    put_le32(template, OFF_ALIGNED_END_1, aligned_end)
    put_le32(template, OFF_UIMAGE_LENGTH, uimage_length)
    put_le32(template, OFF_BINHEADER_LENGTH, BINHEADER_SIZE)
    put_le32(template, OFF_UIMAGE_CRC, crc32(uimage))
    put_le32(template, OFF_ALIGNED_END_2, aligned_end)
    template[OFF_SLOT_STATE:OFF_SLOT_STATE + 4] = SLOT_STATE[slot]

    # 0x110 CRC 覆盖 [0x14, 0x110)，因此必须最后计算；
    # 这样 0x60 的新 Kernel CRC 已包含在 Header CRC 的计算范围内。
    put_le32(template, OFF_HEADER_CRC, crc32(template[0x14:OFF_HEADER_CRC]))

    result = bytes(template) + uimage

    # 写盘前再验证关键字段，避免封装逻辑自身产生不一致结果。
    if get_le32(result, OFF_UIMAGE_LENGTH) != uimage_length:
        raise ValueError("内部校验失败：0x58 长度字段不一致")
    if get_le32(result, OFF_UIMAGE_CRC) != crc32(uimage):
        raise ValueError("内部校验失败：0x60 uImage CRC 不一致")
    if get_le32(result, OFF_HEADER_CRC) != crc32(result[0x14:OFF_HEADER_CRC]):
        raise ValueError("内部校验失败：0x110 Header CRC 不一致")
    if get_le32(result, OFF_ALIGNED_END_1) != aligned_end:
        raise ValueError("内部校验失败：0x54 对齐地址不一致")
    if get_le32(result, OFF_ALIGNED_END_2) != aligned_end:
        raise ValueError("内部校验失败：0x68 对齐地址不一致")

    return result


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    """在目标目录写临时文件并原子替换，失败时不破坏原文件。"""
    parent = path.parent
    if not parent.is_dir():
        raise ValueError(f"输出目录不存在：{parent}")

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp_path, stat.S_IMODE(mode))
        os.replace(temp_path, path)

        # 尽可能同步目录项，确保 rename 的结果落盘。
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            try:
                os.fsync(dir_fd)
            except OSError:
                # 部分文件系统不支持目录 fsync；文件本身已完成原子替换，
                # 不应因此把一次成功写入报告为失败。
                pass
        finally:
            os.close(dir_fd)
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="给标准 Legacy uImage 添加 DT741 480-byte vendor binheader"
    )
    parser.add_argument("--template", required=True, type=Path,
                        help="原厂 480B binheader 模板文件")
    parser.add_argument("--slot", required=True, choices=("a", "b"),
                        help="目标槽位；A=FFFFFFFF，B=00000000")
    parser.add_argument("--output", type=Path,
                        help="输出文件；省略时原子替换输入文件（适合 OpenWrt Build 管线）")
    parser.add_argument("input", type=Path, help="标准 Legacy uImage 文件")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = args.input
    output_path = args.output if args.output is not None else input_path
    template_path = args.template

    try:
        if input_path.is_symlink():
            raise ValueError(f"拒绝直接替换符号链接输入：{input_path}")
        if output_path.resolve() == template_path.resolve():
            raise ValueError("输出文件不能覆盖 480B 模板")
        if input_path.resolve() == template_path.resolve():
            raise ValueError("输入 uImage 不能与 480B 模板是同一个文件")

        input_stat = input_path.stat()
        uimage = input_path.read_bytes()
        template = load_template(template_path)
        result = make_image(uimage, template, args.slot)
        atomic_write(output_path, result, input_stat.st_mode)

        print(
            f"DT741 binheader: slot={args.slot.upper()} "
            f"uImage={len(uimage)} bytes "
            f"binheader={BINHEADER_SIZE} bytes "
            f"output={len(result)} bytes "
            f"aligned_end=0x{(BINHEADER_SIZE + len(uimage) + 15) & ~0x0F:08x}"
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"dt741-binheader: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
