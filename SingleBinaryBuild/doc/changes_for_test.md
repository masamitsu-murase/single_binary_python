# テストに対する変更（v3.14.2 → HEAD）

`C:\my_program\git\bin\git.exe` で `v3.14.2..HEAD` の差分を確認し、**テストコードそのものを修正している箇所のみ**を整理する。

## 1. embeddedimport / 単一バイナリ構成に合わせた参照先修正

- `Lib/test/_test_multiprocessing.py`  
    `multiprocessing.__file__` 依存をやめ、`Lib/multiprocessing` をテストファイル基準で直接参照するよう変更。

- `Lib/test/test_argparse.py`  
    `argparse.__file__` の直接参照をやめ、`Lib/argparse.py` のパスを明示。翻訳テストはダミーオブジェクト（`__file__`, `__name__`）を使って検証するよう変更。

- `Lib/test/test_getopt.py`  
    翻訳テストでモジュール実体ではなく、`Lib/getopt.py` を指すダミーオブジェクトを利用するよう変更。

- `Lib/test/test_optparse.py`  
    翻訳テストでモジュール実体ではなく、`Lib/optparse.py` を指すダミーオブジェクトを利用するよう変更。

- `Lib/test/test_ast/test_ast.py`  
    `ast.__file__` の配置前提を外し、標準ライブラリ探索ルートを `.../Lib` 基準に修正。

- `Lib/test/test_linecache.py`  
    `linecache.__file__` 依存を外し、`linecache.py` を相対的に扱う形へ変更。`getline()` 検証も埋め込みインポータ向けの呼び方へ調整。

- `Lib/test/test_urllib2.py`  
    `urllib.request.__file__` ではなく、テストファイル自身のパスを使うよう変更。

- `Lib/test/test_tabnanny.py`  
    使用説明メッセージで使うスクリプトパス算出方法を変更（`findfile('tabnanny.py')` 依存を外す方向）。

- `Lib/test/test_cmd_line.py`  
    `-X frozen_modules=off` の期待ローダー名を `SourceFileLoader` から `EmbeddedImporter` に変更。

- `Lib/test/test_bdb.py`  
    トレース除外対象に `embeddedimport_helper*` を追加。

- `Lib/test/test_getpath.py`  
    `module_search_paths` の期待値に実行バイナリパス（`python.exe` / `.../bin/python`）を追加し、新しいパス解決仕様に合わせた。

- `Lib/test/test_regrtest.py`  
    Windows 向け `rt.bat` 参照先を `PCbuild\rt.bat` から `SingleBinaryBuild\rt.bat` に変更。

## 2. 利用不可なテスト用 C 拡張・機能への対処（skip / 条件化）

- `Lib/test/test_atexit.py`  
    低メモリ系の `_testcapi` 依存テストを `SkipTest`。

- `Lib/test/test_call.py`  
    `_testinternalcapi` がない環境では再帰マージン検証テストを skip。

- `Lib/test/test_class.py`  
    `_testinternalcapi.has_inline_values` の import を例外処理化し、未提供時は関連アサートを条件付きで実行。

- `Lib/test/test_code.py`  
    `_testcapi.code_offset_to_line` の import を例外処理化し、未提供時は該当テストを skip。

- `Lib/test/test_interpreters/test_api.py`  
    `_testinternalcapi.get_code_var_counts()` 比較を、利用可能時のみ実施する条件付きに変更。

- `Lib/test/test_winconsoleio.py`  
    `_testconsole.write_input` の import を例外処理化（モジュール未提供時に備える）。

- `Lib/test/test_traceback.py`  
    `_testcapi` 依存の例外表示テスト群に `SkipTest` を追加。

- `Lib/test/test_threading.py`  
    `_testcapi` 依存の finalize 系テストを `SkipTest`。

- `Lib/test/test_sys.py`  
    `_stdlib_dir` 前提テストおよび `_testcapi` 前提の JIT テストを `SkipTest`。

- `Lib/test/test_importlib/resources/test_files.py`  
    `c_resources` が必要なケースを `SkipTest`。

- `Lib/test/test_sysconfig.py`  
    Windows での `LIBRARY` 期待値を DLL 名固定から `os.path.basename(sys.executable)` へ変更。加えて venv 前提テストを `SkipTest`。

## 3. その他のテスト安定化調整

- `Lib/test/test_inspect/test_inspect.py`  
    `__spec__.cached` / `__cached__` の出力確認アサートを無効化。

- `Lib/test/test_pyrepl/test_pyrepl.py`  
    import completion 系を `SkipTest` とし、一部相対 import completion ケースをコメントアウト。
