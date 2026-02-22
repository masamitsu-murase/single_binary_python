
import glob
import os
import os.path
from pathlib import Path
import string
import subprocess
import tokenize
import compression.zstd as zstd

THIS_DIR = Path(__file__).parent.resolve()
EXTERNAL_TOOLS_DIR = THIS_DIR / "external_tools"


def check_skip(filename):
    if filename.startswith("test/") or "/test/" in filename:
        return True
    if filename.startswith("__pycache__/") or "/__pycache__/" in filename:
        return True
    if os.path.basename(filename) == "ubuntu.ttf":
        return True
    if filename.startswith("lib2to3/tests/"):
        return True
    if filename.startswith("distutils/tests/"):
        return True
    if filename.startswith("idlelib/idle_test/"):
        return True
    return False


def get_file_data():
    file_list = []

    all_filenames = [
        "email/architecture.rst",
        "pydoc_data/_pydoc.css",
        "tomllib/mypy.ini",
        "turtledemo/turtle.cfg",
        "_pyrepl/mypy.ini",
    ] + list(glob.glob("**/*.py", recursive=True)) + \
        list(glob.glob("lib2to3/*.pickle")) + \
        list(glob.glob("certifi/cacert.pem")) + \
        list(glob.glob("werkzeug/debug/shared/*.*"))
    all_filenames = set(i.replace(os.path.sep, "/") for i in all_filenames)

    for filename in sorted(all_filenames):
        if check_skip(filename):
            continue

        if filename.endswith(".py"):
            # Remove comments
            with open(filename, "rb") as file:
                comments_tuple = tuple(x for x in tokenize.tokenize(file.readline) if x.type == tokenize.COMMENT)
            data = []
            comments_iter = iter(comments_tuple)
            with open(filename, "r", encoding="utf-8") as file:
                comment = next(comments_iter, None)
                for lineno, line in enumerate(file, 1):
                    if comment and comment.start[0] == lineno and comment.end[0] == lineno:
                        if line[comment.end[1]:] == "\n":
                            data.append(line[:comment.start[1]].rstrip() + line[comment.end[1]:])
                        else:
                            data.append(line[:comment.start[1]] + line[comment.end[1]:])
                        comment = next(comments_iter, None)
                    else:
                        data.append(line)
            bindata = "".join(data).encode("utf-8")
        else:
            with open(filename, "rb") as file:
                bindata = file.read()
        file_list.append({
            "filename": filename,
            "data": bindata + b"\0"
        })

    return file_list


def output_list(file_list):
    with open("Modules/embeddedimport_data.c", "w") as file:
        file.write('#include <stddef.h>\n\n')

        file.write("char embeddedimporter_filename[] = {\n")
        for item in file_list:
            file.write("  // " + item["filename"] + "\n")
            filename = item["filename"].encode("ascii")
            for slice_data in (filename[i:(i + 16)] for i in range(0, len(filename), 16)):
                file.write("  " + ",".join(("0x%02x" % ch) for ch in slice_data) + ",\n")
            file.write("  0x00,\n")
        file.write("  0x00\n")
        file.write("};\n\n")

        all_data = b"".join(item["data"] for item in file_list)

        file.write("const size_t embeddedimporter_raw_data_size = %d;\n" % len(all_data))
        file.write("\n")

        level = zstd.CompressionParameter.compression_level.bounds()[1]
        compressed = zstd.compress(all_data, level)
        file.write("const unsigned char embeddedimporter_raw_data_compressed[] = {\n")
        for slice_data in (compressed[i:(i + 16)] for i in range(0, len(compressed), 16)):
            file.write("  " + ",".join(("0x%02x" % ch) for ch in slice_data) + ",\n")
        file.write("};\n")
        file.write("\n")

        file.write("const size_t embeddedimporter_raw_data_compressed_size = %d;\n" % len(compressed))
        file.write("\n")

        offset = 0
        file.write("const size_t embeddedimporter_data_offset[] = {\n")
        for item in file_list:
            file.write("  %d,  // %s\n" % (offset, item["filename"]))
            offset += len(item["data"])
        file.write("};\n")


def output_key_file_for_gperf(file_list):
    acceptable_chars = string.ascii_letters + string.digits + "._/"
    with open("Modules/embeddedimporter_gperf_keyfile.txt", "w") as file:
        file.write("%{\n")
        file.write("#include <stddef.h>\n")

        all_data = b"".join(item["data"] for item in file_list)
        file.write("const size_t embeddedimporter_raw_data_size = %d;\n" % len(all_data))

        level = zstd.CompressionParameter.compression_level.bounds()[1]
        compressed = zstd.compress(all_data, level)
        file.write("const unsigned char embeddedimporter_raw_data_compressed[] = {\n")
        for slice_data in (compressed[i:(i + 16)] for i in range(0, len(compressed), 16)):
            file.write("  " + ",".join(("0x%02x" % ch) for ch in slice_data) + ",\n")
        file.write("};\n")
        file.write("\n")

        file.write("const size_t embeddedimporter_raw_data_compressed_size = %d;\n" % len(compressed))
        file.write("\n")

        file.write("%}\n")

        file.write("struct file_offset {\n")
        file.write("  const char *filename;\n")
        file.write("  size_t offset;\n")
        file.write("  size_t size;\n")
        file.write("};\n")
        file.write("%%\n")

        offset = 0
        for item in file_list:
            filename = item["filename"]
            data = item["data"]
            if any((ch not in acceptable_chars) for ch in filename):
                raise ValueError(f"unacceptable character in filename: {filename}")
            file.write('%s,%d,%d\n' % (filename, offset, len(data) - 1))
            offset += len(data)


if __name__ == "__main__":
    pwd = os.getcwd()
    try:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        os.chdir("..")

        os.chdir("Lib")
        file_list = get_file_data()
        os.chdir("..")
        # output_list(file_list)
        output_key_file_for_gperf(file_list)
        subprocess.run([
            str(EXTERNAL_TOOLS_DIR / "gperf"),
            "-L", "ANSI-C",
            "-t",
            "-N", "embeddedimporter_find_entry",
            "-K", "filename",
            "--output-file=Modules/embeddedimport_data.c",
            "Modules/embeddedimporter_gperf_keyfile.txt"
        ], check=True)
    finally:
        os.chdir(pwd)
