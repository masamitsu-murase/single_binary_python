# テストに対する変更

## 概要

主に embeddedimport があるために、テストコードの変更が必要になっている。  
ここではその内容についてまとめる。

## もともとの Fail テスト

```text
55 tests skipped:
    test.test_asyncio.test_unix_events test.test_gdb.test_backtrace
    test.test_gdb.test_cfunction test.test_gdb.test_cfunction_full
    test.test_gdb.test_misc test.test_gdb.test_pretty_print
    test.test_multiprocessing_fork.test_manager
    test.test_multiprocessing_fork.test_misc
    test.test_multiprocessing_fork.test_processes
    test.test_multiprocessing_fork.test_threads
    test.test_multiprocessing_forkserver.test_manager
    test.test_multiprocessing_forkserver.test_misc
    test.test_multiprocessing_forkserver.test_processes
    test.test_multiprocessing_forkserver.test_threads test_android
    test_apple test_bigmem test_bytes test_compileall test_crossinterp
    test_dbm_gnu test_dbm_ndbm test_devpoll test_epoll test_fcntl
    test_fileutils test_fork1 test_free_threading test_grp test_import
    test_ioctl test_kqueue test_monitoring test_opcache test_openpty
    test_optimizer test_perf_profiler test_perfmaps test_pkgutil
    test_poll test_pty test_pwd test_pyclbr test_resource
    test_stable_abi_ctypes test_syslog test_termios
    test_thread_local_bytecode test_threadsignals test_tty
    test_type_cache test_wait3 test_wait4 test_xxlimited
    test_xxtestfuzz

10 tests skipped (resource denied):
    test_curses test_peg_generator test_smtpnet test_socketserver
    test_tkinter test_ttk test_urllib2net test_urllibnet test_winsound
    test_zipfile64

34 tests failed:
    test.test_inspect.test_inspect
    test.test_multiprocessing_spawn.test_misc test_argparse test_ast
    test_atexit test_bdb test_builtin test_call test_capi test_class
    test_code test_docxmlrpc test_dtrace test_external_inspection
    test_functools test_getopt test_getpath test_interpreters
    test_linecache test_mimetypes test_optparse test_pyrepl test_re
    test_regrtest test_shlex test_struct test_sys test_sysconfig
    test_tabnanny test_threading test_traceback test_urllib2
    test_winconsoleio test_zoneinfo
```

## ログ精査結果（要因分類）

分類は以下の3種類で記載する。

- A: embeddedimport により、物理的なファイルにアクセスできなくなっている
- B: _testcapi, _testinternalcapi など、_testxxxx というモジュールが存在しないことによるエラー
- C: それ以外

### A のテスト

- test.test_inspect.test_inspect  
    `__spec__.cached` が `None`（`Cached:` が出ず、埋め込み loader になっている）
- test_argparse  
    `argparse.__file__` が `...\sbpython.exe\argparse.py` を指し `FileNotFoundError`、翻訳 msgid 取得も空
- test_ast  
    標準ライブラリ探索先が `...\sbpython.exe` になり `os.listdir()` が `NotADirectoryError`
- test_docxmlrpc  
    `xmlrpc` が参照する `_pydoc.css` を `...\sbpython.exe\...` から開けず `FileNotFoundError`
- test_getopt  
    翻訳 msgid 取得結果が空（期待スナップショット不一致）
- test_linecache  
    `linecache` が埋め込み側パスで期待どおりソース取得できず、空行/キャッシュ関連が不一致
- test_optparse  
    翻訳 msgid 取得結果が空（期待スナップショット不一致）
- test_pyrepl  
    import 補完が部分一致止まり（モジュール列挙が不十分で `pathlib` などへ補完不能）
- test_urllib2  
    `file://` で `urllib/request.py` 実ファイルを開こうとして `...\sbpython.exe\urllib\request.py` が見つからず失敗

### B のテスト

- test_atexit  
    `_testcapi` 不在により期待 `MemoryError` ではなく `ModuleNotFoundError`
- test_call  
    `_testinternalcapi` が `None` 扱いで `AttributeError`
- test_capi  
    `_testcapi` が無くテストモジュール import 失敗
- test_class  
    `_testinternalcapi` が無くテストモジュール import 失敗
- test_code  
    `_testcapi` が無くテストモジュール import 失敗
- test_interpreters  
    `_testinternalcapi` が `None` で `get_code_var_counts` 呼び出し失敗
- test_threading  
    `_testcapi` 不在でサブプロセスが `ModuleNotFoundError`
- test_traceback  
    多数ケースが `_testcapi` 不在で `ModuleNotFoundError`
- test_winconsoleio  
    `_testconsole` 不在で import 失敗

### C のテスト

- test.test_multiprocessing_spawn.test_misc  
    `sys.executable=None` で `embeddedimport_helper._to_os_path()` が `TypeError`、および `multiprocessing.__init__` 名称前提の不一致
- test_bdb  
    トレースイベント列不一致（期待 `line` に対し `call`）
- test_builtin  
    `__import__('string\x00')` で `embeddedimport_helper` 側が `SystemError` を返し、期待例外不一致
- test_dtrace  
    保存ログでは失敗せず（skip のみで PASS）
- test_external_inspection  
    `AsyncioDebug section unavailable`（外部検査情報が無い）
- test_functools  
    lazy import テストで `os` が起動時点で既に import 済み
- test_getpath  
    `module_search_paths` に実行ファイルパスが混入し多数アサーション不一致
- test_mimetypes  
    lazy import テストで `os` が起動時点で既に import 済み
- test_re  
    警告発生位置 `w.filename` が `embeddedimport_helper.py` となり期待ファイルと不一致
- test_regrtest  
    `PCbuild\amd64\python.exe` 前提のバッチ実行がパス不一致で失敗
- test_shlex  
    lazy import テストで `os` が起動時点で既に import 済み
- test_struct  
    保存ログでは失敗せず（skip 1 件のみで PASS）
- test_sys  
    `sys._stdlib_dir` が `None`（`TypeError`）が主因（JIT 側では `_testcapi` 不在も発生）
- test_sysconfig  
    venv 実行ファイル生成/起動失敗（`FileNotFoundError`）とライブラリ名期待不一致（`sbpython.exe` vs `python314.dll`）
- test_tabnanny  
    usage 表示のスクリプトパスが `Lib\tabnanny.py` 期待に対して `sbpython.exe\tabnanny.py`
- test_zoneinfo  
    warning 発生位置ファイル名が `zoneinfo/__init__.py` 側になり、期待テストファイルと不一致

## B分類テストへの対応（_testxxxx）

### グローバルスコープで `import _testxxxx` を行っているもの

test_capi を除き、個別に対応。

- `test_capi`
    - `Lib/test/test_capi/*`（複数ファイル）
    - 例: `import _testcapi`, `import _testinternalcapi`, `import _testlimitedcapi`
- `test_code`
    - `Lib/test/test_code.py`
    - `from _testcapi import code_offset_to_line`
- `test_winconsoleio`
    - `Lib/test/test_winconsoleio.py`
    - `from _testconsole import write_input`

### それ以外（fail テスト側に SkipTest を追加）

以下は、fail していたテスト内で `_testxxxx` 依存を回避するため、
`raise unittest.SkipTest("_testxxxx is not supported")` を追加した。

- `test_atexit`
    - `Lib/test/test_atexit.py`
    - `test_atexit_with_low_memory` の先頭に追加
- `test_threading`
    - `Lib/test/test_threading.py`
    - `test_finalize_daemon_thread_hang` の先頭に追加
- `test_traceback`
    - `Lib/test/test_traceback.py`
    - 失敗系で `_testcapi` を import する箇所（`get_report()` / `check_traceback_format()` / `test_unhashable()` など）に追加

補足:
- `test_interpreters` は fail テスト内に `import _testxxxx` の記述がなく、
    `_testinternalcapi` は別モジュール経由で参照されているため、このルールでの直接挿入対象はなし。
