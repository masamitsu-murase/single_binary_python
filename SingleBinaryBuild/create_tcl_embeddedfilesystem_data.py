
import os
import pathlib
import sys
from dataclasses import dataclass
from compression import zstd as zstd_mod


@dataclass
class Entry:
    name: str
    is_dir: bool
    offset: int
    size: int


def _compress_zstd(data: bytes) -> bytes:
    level = zstd_mod.CompressionParameter.compression_level.bounds()[1]
    return zstd_mod.compress(data, level=level)


def _iter_files(base: pathlib.Path) -> tuple[list[Entry], bytes]:
    entries: list[Entry] = []
    payload = bytearray()
    seen_dirs: set[str] = set()

    for top in ("tcl8.6", "tk8.6"):
        top_dir = base / top
        if not top_dir.is_dir():
            raise FileNotFoundError(f"Missing directory: {top_dir}")

        for root, dirs, files in os.walk(top_dir):
            files.sort()

            root_path = pathlib.Path(root)
            root_rel = root_path.relative_to(base).as_posix()
            if root_rel not in seen_dirs:
                seen_dirs.add(root_rel)
                entries.append(Entry(root_rel, True, 0, 0))

            for filename in files:
                file_path = root_path / filename
                rel_name = file_path.relative_to(base).as_posix()
                content = file_path.read_bytes()
                offset = len(payload)
                payload.extend(content)
                entries.append(Entry(rel_name, False, offset, len(content)))

    entries.sort(key=lambda e: (e.name, 0 if e.is_dir else 1))
    return entries, bytes(payload)


def _hex_array(data: bytes, width: int = 12) -> str:
    if not data:
        return ""
    items = [f"0x{b:02X}" for b in data]
    lines = []
    for i in range(0, len(items), width):
        lines.append("    " + ", ".join(items[i : i + width]))
    return ",\n".join(lines)


def _c_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _generate_c(entries: list[Entry], compressed: bytes, uncompressed_size: int) -> str:
    lines: list[str] = []

    lines.append('#include "_tkinter_tclEmbeddedFilesystemData.h"')
    lines.append("")
    lines.append('#include "Python.h"')
    lines.append("#include <string.h>")
    lines.append("")
    lines.append("#include <zstd.h>")
    lines.append("")

    lines.append("const unsigned char gCompressedData[] = {")
    hex_data = _hex_array(compressed)
    if hex_data:
        lines.append(hex_data)
    lines.append("};")
    lines.append("unsigned char *gUncompressedData = NULL;")
    lines.append("const size_t gCompressedDataSize = sizeof(gCompressedData);")
    lines.append(f"const size_t gUncompressedDataSize = {uncompressed_size};")
    lines.append("")

    lines.append("EmbeddedFileInfo gEmbeddedFileInfo[] = {")
    for e in entries:
        file_type = "EMBEDDED_FILE_INFO_TYPE_DIRECTORY" if e.is_dir else "EMBEDDED_FILE_INFO_TYPE_FILE"
        lines.append(
            f'    {{"{_c_escape(e.name)}", {file_type}, NULL, {e.size}, {e.offset}}},'
        )
    lines.append("};")
    lines.append("")
    lines.append("const size_t gEmbeddedFileInfoCount = sizeof(gEmbeddedFileInfo) / sizeof(gEmbeddedFileInfo[0]);")
    lines.append("")

    lines.append("int")
    lines.append("EmbeddedFileInfoDataInitialize(void)")
    lines.append("{")
    lines.append("    size_t i;")
    lines.append("")
    lines.append("    if (gUncompressedData != NULL) {")
    lines.append("        return 0;")
    lines.append("    }")
    lines.append("")
    lines.append("    if (gUncompressedDataSize == 0) {")
    lines.append("        gUncompressedData = (unsigned char *)PyMem_Malloc(1);")
    lines.append("        if (gUncompressedData == NULL) {")
    lines.append("            return -1;")
    lines.append("        }")
    lines.append("    }")
    lines.append("    else {")
    lines.append("        size_t result;")
    lines.append("")
    lines.append("        gUncompressedData = (unsigned char *)PyMem_Malloc(gUncompressedDataSize);")
    lines.append("        if (gUncompressedData == NULL) {")
    lines.append("            return -1;")
    lines.append("        }")
    lines.append("")
    lines.append("        result = ZSTD_decompress(gUncompressedData,")
    lines.append("                                 gUncompressedDataSize,")
    lines.append("                                 gCompressedData,")
    lines.append("                                 gCompressedDataSize);")
    lines.append("        if (ZSTD_isError(result) || result != gUncompressedDataSize) {")
    lines.append("            PyMem_Free(gUncompressedData);")
    lines.append("            gUncompressedData = NULL;")
    lines.append("            return -1;")
    lines.append("        }")
    lines.append("    }")
    lines.append("")
    lines.append("    for (i = 0; i < gEmbeddedFileInfoCount; i++) {")
    lines.append("        if (gEmbeddedFileInfo[i].type == EMBEDDED_FILE_INFO_TYPE_FILE) {")
    lines.append("            gEmbeddedFileInfo[i].file_content = gUncompressedData + gEmbeddedFileInfo[i].data_offset;")
    lines.append("        }")
    lines.append("    }")
    lines.append("")
    lines.append("    return 0;")
    lines.append("}")

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: create_tcl_embeddedfilesystem_data.py <tcltk-lib-base-dir> <output-c-file>",
            file=sys.stderr,
        )
        return 2

    base_dir = pathlib.Path(argv[1]).resolve()
    out_file = pathlib.Path(argv[2]).resolve()

    entries, payload = _iter_files(base_dir)
    compressed = _compress_zstd(payload)
    c_source = _generate_c(entries, compressed, len(payload))

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(c_source, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
