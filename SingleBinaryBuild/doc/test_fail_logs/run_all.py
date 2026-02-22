from pathlib import Path
import subprocess
import sys


def run_test(test_name):
    res = subprocess.run([sys.executable, "-m", "test.regrtest", "-vv", test_name],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return res.stdout

def main():
    test_names = [
        "test.test_inspect.test_inspect",
        "test.test_multiprocessing_spawn.test_misc",
        "test_argparse",
        "test_ast",
        "test_atexit",
        "test_bdb",
        "test_builtin",
        "test_call",
        "test_capi",
        "test_class",
        "test_code",
        "test_docxmlrpc",
        "test_dtrace",
        "test_external_inspection",
        "test_functools",
        "test_getopt",
        "test_getpath",
        "test_interpreters",
        "test_linecache",
        "test_mimetypes",
        "test_optparse",
        "test_pyrepl",
        "test_re",
        "test_regrtest",
        "test_shlex",
        "test_struct",
        "test_sys",
        "test_sysconfig",
        "test_tabnanny",
        "test_threading",
        "test_traceback",
        "test_urllib2",
        "test_winconsoleio",
        "test_zoneinfo",
    ]

    for test_name in test_names:
        print(f"Running {test_name}...")
        output = run_test(test_name)

        path = Path(__file__).parent / f"{test_name.replace('.', '_')}.log"
        with path.open("w") as f:
            f.write(output)


if __name__ == "__main__":
    main()
