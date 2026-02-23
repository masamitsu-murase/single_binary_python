# Single Binary Python — 設計と変更点

## 概要

本プロジェクトは、CPython 3.14 を単一の実行ファイル（`python.exe`）として動作させるためのビルド構成です。

通常の CPython ビルド（`PCbuild/`）では、インタプリタコア（`python314.dll`）、各拡張モジュール（`.pyd` ファイル群）、外部 DLL（OpenSSL、libffi、Tcl/Tk 等）が個別のファイルとして生成されます。本プロジェクトでは、これらをすべて**静的ライブラリ**としてビルドし、最終的に 1 つの `python.exe` にリンクします。

加えて、Python 標準ライブラリの `.py` ファイル群を実行ファイル内に埋め込む **EmbeddedImporter** を実装し、ファイルシステムに依存しない完全な単一バイナリ実行環境を実現しています。

---

## 目次

1. [ビルド方法](#ビルド方法)
2. [PCbuild と SingleBinaryBuild の比較](#pcbuild-と-singlebinarybuild-の比較)
3. [静的ビルドの仕組み](#静的ビルドの仕組み)
4. [外部ライブラリのビルド](#外部ライブラリのビルド)
5. [CPython 本体への変更](#cpython-本体への変更)
6. [EmbeddedImporter](#embeddedimporter)
7. [SingleBinaryBuild 固有ファイル一覧](#singlebinarybuild-固有ファイル一覧)

---

## ビルド方法

```bat
SingleBinaryBuild.bat
```

内部では以下が実行されます：

```bat
call SingleBinaryBuild\build.bat -c Release -p x64 -t Build
```

`build.bat` は MSBuild を呼び出して `pcbuild.sln` をビルドします。`build.bat` 自体は `PCbuild/build.bat` のフォークであり、出力先が `SingleBinaryBuild\amd64\` に変更されています。

### ビルド前の準備

外部ライブラリのビルドは、MSBuild によるメインビルドの前に個別に行う必要があります。詳細は「[外部ライブラリのビルド](#外部ライブラリのビルド)」を参照してください。

### ビルド出力

```
SingleBinaryBuild\amd64\
├── python.exe              ← 単一バイナリ（すべてが静的リンク済み）
├── pythoncore_static.lib   ← インタプリタコア（静的ライブラリ）
├── *_builtin.lib           ← 各拡張モジュール（静的ライブラリ）
└── （DLL ファイルは不要）
```

---

## PCbuild と SingleBinaryBuild の比較

`SingleBinaryBuild/` は `PCbuild/` のフォークです。ソリューションファイル（`pcbuild.sln`）に含まれるプロジェクトの一覧は同一であり、個々の `.vcxproj` ファイルや `.props` ファイルに対して、静的ビルドに必要な変更を加えています。

### 変更の全体像

| 変更カテゴリ | 対象ファイル | 変更内容 |
|---|---|---|
| CRT リンク方式 | `pyproject.props` | `/MD`（動的 CRT）→ `/MT`（静的 CRT） |
| インタプリタコア | `pythoncore.vcxproj` | DLL → StaticLibrary、EmbeddedImporter 追加 |
| 実行ファイル | `python.vcxproj` | 全静的モジュールをリンク |
| 拡張モジュール（23 個） | 各 `.vcxproj` | DLL → StaticLibrary（`pymodule_static.props` 経由） |
| OpenSSL | `openssl.props` | DLL コピー無効化 |
| libffi | `libffi.props` | `libffi-8.lib`（DLL）→ `libffi_convenience.lib`（静的） |
| ビルド出力パス | `python.props` | `PCbuild\` → `SingleBinaryBuild\` |
| 新規ファイル群 | 多数 | Props、自動化スクリプト、EmbeddedImporter、静的モジュール用 vcxproj 群 |

### 1. pyproject.props — CRT リンク方式

通常の CPython は MSVC 動的ランタイム（`/MD`、`vcruntime140.dll` 依存）を使用しますが、単一バイナリ化のためには**静的 CRT**（`/MT`）に切り替える必要があります。これにより、最終的な `python.exe` は `vcruntime140.dll` / `ucrtbase.dll` に依存しなくなります。

| 構成 | PCbuild | SingleBinaryBuild |
|---|---|---|
| Release | `MultiThreadedDLL`（`/MD`） | `MultiThreaded`（`/MT`） |
| Debug | `MultiThreadedDebugDLL`（`/MDd`） | `MultiThreadedDebug`（`/MTd`） |

> **背景**: `/MT` と `/MD` が混在するとリンクエラーになります。したがって、すべてのライブラリ（pythoncore、拡張モジュール、外部ライブラリ）を一貫して `/MT` でビルドする必要があります。

### 2. pythoncore.vcxproj — インタプリタコア

通常は `python314.dll` として生成されるインタプリタコアを、静的ライブラリ `pythoncore_static.lib` に変更しています。

| 項目 | PCbuild | SingleBinaryBuild |
|---|---|---|
| `ConfigurationType` | `DynamicLibrary` | `StaticLibrary` |
| `TargetName` | `python314` | `pythoncore_static` |
| プリプロセッサ（追加） | `_USRDLL;Py_ENABLE_SHARED` | `Py_SINGLE_BINARY_BUILD;Py_NO_ENABLE_SHARED` |
| 追加インクルード | — | `$(zstdDir)lib`（zstd ヘッダ） |
| 追加ソースファイル | — | `embeddedimport.c`、`embeddedimport_data.c` |

> **背景**: `Py_ENABLE_SHARED` は `__declspec(dllexport)` を有効にするマクロです。静的ライブラリでは不要であり、`Py_NO_ENABLE_SHARED` で無効化します。`Py_BUILD_CORE_BUILTIN` は、拡張モジュールが DLL ではなくインタプリタ本体に組み込まれていることを示します。

### 3. python.vcxproj — 実行ファイル

通常の `python.exe` は小さなランチャーで、`python314.dll` を動的にロードします。SingleBinaryBuild では、すべての静的ライブラリをここにリンクします。

| 項目 | PCbuild | SingleBinaryBuild |
|---|---|---|
| 追加 Props | — | `python_modules_link.props` |
| プリプロセッサ（追加） | — | `Py_BUILD_CORE_BUILTIN;Py_SINGLE_BINARY_BUILD` |
| リンク依存 | `pythoncore` のみ | `pythoncore` + 23 個の静的拡張モジュール + 外部/システムライブラリ |

`python_modules_link.props` には、すべての静的モジュール（`*_builtin.lib`）、外部ライブラリ（`libffi_convenience.lib`、`libcrypto.lib`、`libssl.lib`）、および必要なシステムライブラリ（`ws2_32.lib`、`crypt32.lib`、`bcrypt.lib` 等）が列挙されています。

### 4. 拡張モジュール — 共通パターン

通常 `.pyd`（DLL）としてビルドされる拡張モジュールを、すべて `.lib`（静的ライブラリ）に変更しています。この変換は `pymodule_static.props` を各 `.vcxproj` にインポートすることで行われます。

| 項目 | PCbuild | SingleBinaryBuild |
|---|---|---|
| `ConfigurationType` | `DynamicLibrary` | `StaticLibrary` |
| `TargetExt` | `.pyd` | `.lib` |
| `TargetName` | `<projectname>` | `<projectname>_builtin` |
| プリプロセッサ | — | `Py_BUILD_CORE_BUILTIN;Py_SINGLE_BINARY_BUILD;Py_NO_ENABLE_SHARED` |

**静的リンク対象の全 23 拡張モジュール**:

`_asyncio`, `_bz2`, `_ctypes`, `_decimal`, `_elementtree`, `_hashlib`, `_lzma`, `_multiprocessing`, `_overlapped`, `_queue`, `_remote_debugging`, `_socket`, `_sqlite3`, `_ssl`, `_tkinter`, `_uuid`, `_wmi`, `_zoneinfo`, `_zstd`, `pyexpat`, `select`, `unicodedata`, `winsound`

`zlib-ng` や `sqlite3` は外部/サポートライブラリとしてリンクされ、上記の「拡張モジュール数」には含めない。

一部のモジュールには追加の変更があります：

| モジュール | 追加変更 |
|---|---|
| `sqlite3` | `SQLITE_API=__declspec(dllexport)` を削除（静的ライブラリでは不要） |
| `_ctypes` | プリプロセッサに `FFI_BUILDING` を追加（libffi 静的リンク時に必要） |
| `_hashlib` | `ws2_32.lib` のリンクを削除（`python_modules_link.props` 側で一括指定） |

### 5. python.props — ビルドパス

| 項目 | PCbuild | SingleBinaryBuild |
|---|---|---|
| `BuildPath` | `$(PySourcePath)PCbuild\amd64\` | `$(PySourcePath)SingleBinaryBuild\amd64\` |
| `libffiDir` | `$(ExternalsDir)libffi-3.4.4\` | `$(ExternalsDir)libffi\` |

### 6. openssl.props — DLL コピー無効化

`_CopySSLDLL` ターゲットの `Copy` 要素がコメントアウトされています。OpenSSL は静的リンクされるため、DLL のコピーは不要です。

### 7. libffi.props — 静的ライブラリへの切替

| 項目 | PCbuild | SingleBinaryBuild |
|---|---|---|
| `AdditionalDependencies` | `libffi-8.lib`（DLL インポートライブラリ） | `libffi_convenience.lib`（静的ライブラリ） |
| `_CopyLIBFFIDLL` | DLL をコピー | コメントアウト |

### 8. 備考

- `Directory.Build.props` / `Directory.Build.targets` は空のプレースホルダ（MSBuild の親ディレクトリ探索を防止）。
- `SingleBinaryBuild/` 側には、`PCbuild/` 由来の構成に加えて単一バイナリ向けの `.vcxproj` / `.props` / スクリプトが追加されている。

---

## 静的ビルドの仕組み

### pymodule_static.props

静的ビルドの中核となるプロパティシートです。各拡張モジュールの `.vcxproj` で `pyproject.props` の直後にインポートされます。

```xml
<PropertyGroup Label="Configuration">
    <ConfigurationType>StaticLibrary</ConfigurationType>
</PropertyGroup>
<PropertyGroup>
    <TargetExt>.lib</TargetExt>
    <TargetName>$(ProjectName)_builtin</TargetName>
</PropertyGroup>
<ItemDefinitionGroup>
    <ClCompile>
        <PreprocessorDefinitions>
            Py_BUILD_CORE_BUILTIN;Py_SINGLE_BINARY_BUILD;Py_NO_ENABLE_SHARED;%(PreprocessorDefinitions)
        </PreprocessorDefinitions>
    </ClCompile>
</ItemDefinitionGroup>
```

### python_modules_link.props

`python.exe` のリンク設定を定義するプロパティシートです。以下を含みます：

- 23 個の静的拡張モジュール `.lib` ファイル（`AdditionalDependencies`）
- 外部ライブラリ（`libffi_convenience.lib`、`libcrypto.lib`、`libssl.lib`）
- システムライブラリ（`ws2_32.lib`、`crypt32.lib`、`bcrypt.lib`、`iphlpapi.lib` 等）
- 各モジュール `.vcxproj` への `ProjectReference`（ビルド順序の保証用、`ReferenceOutputAssembly=false`）

### PC/config.c — 組み込みモジュール登録

静的リンクされた拡張モジュールは、`PC/config.c` の `_PyImport_Inittab[]` に登録する必要があります。これにより、Python の `import` 文がファイルシステムを検索する前に、組み込みモジュールとしてロードできるようになります。

登録されている静的モジュール（`-- ADDMODULE MARKER 2 --` 以降）：

```c
{"_asyncio", PyInit__asyncio},
{"_bz2", PyInit__bz2},
{"_hashlib", PyInit__hashlib},
{"_ctypes", PyInit__ctypes},
{"_decimal", PyInit__decimal},
{"_elementtree", PyInit__elementtree},
{"_lzma", PyInit__lzma},
{"_multiprocessing", PyInit__multiprocessing},
{"_overlapped", PyInit__overlapped},
{"_queue", PyInit__queue},
{"_remote_debugging", PyInit__remote_debugging},
{"_socket", PyInit__socket},
{"_sqlite3", PyInit__sqlite3},
{"_ssl", PyInit__ssl},
{"_uuid", PyInit__uuid},
{"_wmi", PyInit__wmi},
{"_zoneinfo", PyInit__zoneinfo},
{"_zstd", PyInit__zstd},
{"pyexpat", PyInit_pyexpat},
{"select", PyInit_select},
{"unicodedata", PyInit_unicodedata},
{"winsound", PyInit_winsound},
{"_tkinter", PyInit__tkinter},
```

---

## 外部ライブラリのビルド

外部ライブラリはすべて**静的ライブラリ**かつ **`/MT`（静的 CRT）** でビルドする必要があります。通常の CPython ビルド（PCbuild）では DLL として生成されるものが多いため、ビルド手順が異なります。

### 一覧

| ライブラリ | ソースディレクトリ | PCbuild での形態 | SingleBinaryBuild での形態 | ビルド方法 |
|---|---|---|---|---|
| OpenSSL 3.0.18 | `externals/openssl-3.0.18/` | DLL | **静的 `.lib`** | `prepare_ssl.bat` |
| libffi 3.4.4 | `externals/libffi-3.4.4/` | DLL | **静的 `.lib`** | `prepare_libffi.bat`（Cygwin 必須） |
| Tcl 8.6.15 | `externals/tcl-core-8.6.15.0/` | DLL | **静的 `.lib`** | `prepare_tcltk.bat` |
| Tk 8.6.15 | `externals/tk-8.6.15.0/` | DLL | **静的 `.lib`** | `prepare_tcltk.bat` |
| SQLite 3.50.4 | `externals/sqlite-3.50.4.0/` | DLL (`.pyd`) | **静的 `.lib`** | MSBuild（vcxproj 内で直接コンパイル） |
| zlib-ng 2.2.4 | `externals/zlib-ng-2.2.4/` | 静的 `.lib` | 静的 `.lib`（同一） | MSBuild（vcxproj 内で直接コンパイル） |
| liblzma (xz) 5.2.5 | `externals/xz-5.2.5/` | 静的 `.lib` | 静的 `.lib`（同一） | MSBuild（vcxproj 内で直接コンパイル） |
| bzip2 1.0.8 | `externals/bzip2-1.0.8/` | DLL (`.pyd`) | **静的 `.lib`** | MSBuild（vcxproj 内で直接コンパイル） |
| mpdecimal 4.0.0 | `externals/mpdecimal-4.0.0/` | DLL (`.pyd`) | **静的 `.lib`** | MSBuild（vcxproj 内で直接コンパイル） |
| zstd 1.5.7 | `externals/zstd-1.5.7/` | DLL (`.pyd`) | **静的 `.lib`** | MSBuild（vcxproj 内で直接コンパイル） |

### OpenSSL

#### PCbuild での手順

```
perl Configure VC-WIN64A no-asm no-uplink
```

共有ライブラリ（`libcrypto-3.dll`、`libssl-3.dll`）を生成し、出力ディレクトリにコピーします。

#### SingleBinaryBuild での手順

```
perl Configure VC-WIN64A no-asm no-uplink no-shared
```

**`no-shared`** フラグにより、静的ライブラリのみ（`libcrypto.lib`、`libssl.lib`）を生成します。DLL は生成されません。`openssl.props` で DLL コピーターゲットがコメントアウトされています。

ビルド済みバイナリは `externals/openssl-bin-3.0.18/` に配置されます。

### libffi

#### PCbuild での手順

```bash
./configure CC='msvcc.sh ...' CPPFLAGS='-DFFI_BUILDING_DLL' ...
```

共有ライブラリ（`libffi-8.dll`）を生成します。

#### SingleBinaryBuild での手順

```bash
./configure --disable-shared --enable-static \
    CC='msvcc.sh -DUSE_STATIC_RTL ...' \
    CPPFLAGS='-DFFI_BUILDING' ...
```

- **`--disable-shared --enable-static`**: 静的ライブラリのみ生成
- **`-DUSE_STATIC_RTL`**: `/MT` での CRT リンク
- **`-DFFI_BUILDING`**（`-DFFI_BUILDING_DLL` ではなく）: DLL エクスポートなし
- 出力: `libffi_convenience.lib`

> **注意**: libffi のビルドには **Cygwin** が必要です。`configure` スクリプトは POSIX 環境で実行され、`msvcc.sh` ラッパーを通じて MSVC コンパイラを呼び出します。

### Tcl/Tk

#### PCbuild での手順

```bat
nmake -f makefile.vc OPTS=msvcrt core shell dlls
nmake -f makefile.vc OPTS=msvcrt install-binaries install-libraries
```

`OPTS=msvcrt` で動的 CRT にリンクし、DLL（`tcl86t.dll`、`tk86t.dll`）を生成します。

#### SingleBinaryBuild での手順

```bat
nmake -f makefile.vc OPTS=static core
nmake -f makefile.vc OPTS=static install-libraries
```

- **`OPTS=static`**: 静的ライブラリとしてビルド
- `core` のみビルド（`shell`、`dlls` は不要）
- `install-libraries` のみ（`install-binaries` は不要）

ビルド済みバイナリは `externals/tcltk-8.6.15.0/` に配置されます。

### MSBuild 管理のライブラリ（SQLite, zlib-ng, liblzma, bzip2, mpdecimal, zstd）

これらのライブラリは `.vcxproj` ファイル内でソースコードを直接コンパイルする構成です。SingleBinaryBuild では `pymodule_static.props` のインポートにより自動的に `StaticLibrary` としてビルドされるため、個別のビルド手順は不要です。

---

## CPython 本体への変更

### Python/import.c — EmbeddedImporter の初期化

`_PyImport_InitExternal()` に `init_embeddedimport()` を追加し、`sys.path_hooks` の先頭に `EmbeddedImporter` を登録します：

```c
PyStatus _PyImport_InitExternal(PyThreadState *tstate) {
    init_importlib_external(tstate->interp);    // 標準 importlib
    init_zipimport(tstate, verbose);            // zipimport フック
    init_embeddedimport(tstate, verbose);       // ← 追加
}
```

`init_embeddedimport()` は `embeddedimport.embeddedimporter` を `sys.path_hooks` の先頭（index 0）に挿入します。これにより、インポート解決の優先順位は `EmbeddedImporter` → `zipimporter` → `FileFinder` → ... となります。

### PC/config.c — 組み込みモジュール登録

前述の通り、静的リンクされた拡張モジュールと `embeddedimport` モジュールの `PyInit_*` 関数を `_PyImport_Inittab[]` に追加しています。

---

## EmbeddedImporter

Python 標準ライブラリの `.py` ファイルを実行ファイル内に埋め込み、ファイルシステム無しでインポート可能にする仕組みです。C 拡張モジュール（`embeddedimport.c`）と Python ヘルパー（`embeddedimport_helper.py`）の 2 層構成で実装されています。

### 主な特徴

- **zstd 圧縮**: 約 9.4 MB のソースを約 1.6 MB に圧縮して埋め込み
- **gperf 完全ハッシュ**: ファイル名から O(1) でデータ位置を検索
- **PEP 489 マルチフェーズ初期化**: サブインタプリタ対応
- **PEP 451 準拠**: `find_spec` / `create_module` / `exec_module` による path-hook 型インポーター

### 詳細ドキュメント

EmbeddedImporter の実装詳細（データ生成パイプライン、C モジュール API、Python ヘルパーの設計、初期化フローなど）は、以下のドキュメントを参照してください：

→ **[embeddedimporter_summary.md](./embeddedimporter_summary.md)**

---

## SingleBinaryBuild 固有ファイル一覧

`PCbuild/` には存在せず、`SingleBinaryBuild/` にのみ存在するファイルの一覧です。

### ビルドインフラ

| ファイル | 説明 |
|---|---|
| [pymodule_static.props](../pymodule_static.props) | 拡張モジュールを StaticLibrary に変換する共通プロパティシート |
| [python_modules_link.props](../python_modules_link.props) | python.exe のリンク設定（全静的モジュール + 外部ライブラリ + システムライブラリ） |

### 自動化スクリプト

| ファイル | 説明 |
|---|---|
| [create_embeddedimporter_data.py](../create_embeddedimporter_data.py) | Lib/ 配下の .py ファイルを収集・圧縮し、gperf 入力ファイルを生成 |
| [create_tcl_embeddedfilesystem_data.py](../create_tcl_embeddedfilesystem_data.py) | Tcl/Tk ライブラリファイルを収集し、埋め込み用 C データを生成 |
| [prepare_ssl.bat](../prepare_ssl.bat) | OpenSSL を静的リンク向け設定でビルドする準備スクリプト |
| [prepare_ssl.py](../prepare_ssl.py) | OpenSSL 準備処理の本体（バージョン判定・取得・設定処理） |
| [prepare_libffi.bat](../prepare_libffi.bat) | libffi を静的ライブラリとしてビルドする準備スクリプト |
| [prepare_tcltk.bat](../prepare_tcltk.bat) | Tcl/Tk を静的ライブラリとしてビルドする準備スクリプト |
| [get_external.py](../get_external.py) | 外部依存の取得処理を行う補助スクリプト |

### ドキュメント

| ファイル | 説明 |
|---|---|
| [changes_from_v3.14.2.md](./changes_from_v3.14.2.md) | `v3.14.2` から現行 HEAD までの主要差分サマリ |
