# EmbeddedImporter 実装の詳細（Python 3.13 対応版）

## 概要

EmbeddedImporter は、Python の標準ライブラリや外部ライブラリのソースコードを実行ファイル内に埋め込み、単一の実行ファイルで Python を動作させるための仕組みです。C 拡張モジュール（`embeddedimport.c`）と Python ヘルパー（`embeddedimport_helper.py`）の 2 層構成で実装されています。

### 主な特徴

- **単一バイナリ化**: `Lib/` 配下のすべてのライブラリソースを実行ファイルに埋め込む
- **zstd 圧縮**: ファイルデータを zstd 最高レベルで圧縮して埋め込む（約 9.4 MB → 約 1.6 MB）
- **gperf 完全ハッシュ**: ファイル名から O(1) でオフセット/サイズを検索
- **PEP 489 マルチフェーズ初期化**: サブインタプリタ対応（`Py_mod_multiple_interpreters`）
- **PEP 451 準拠**: `find_spec` / `create_module` / `exec_module` による path-hook 型インポーター
- **2つのデータソース対応**:
  - コンパイル時に埋め込まれた静的データ（gperf テーブル経由）
  - Windows リソースとして追加された動的データ（`Py_BUILD_RESOURCE_EMBEDDED_MODULE` 定義時のみ・未完成）

---

## アーキテクチャ

### 全体構成図

```
┌─────────────────────────────────────────────────────────────┐
│  Python 起動                                                 │
│  _PyImport_InitExternal()          [Python/import.c]         │
│    ├─ init_importlib_external()    … 標準 importlib          │
│    ├─ init_zipimport()             … zipimport hook          │
│    └─ init_embeddedimport()        … ★ EmbeddedImporter      │
│         ├─ import embeddedimport   … C builtin モジュール     │
│         │    └─ embeddedimport_exec()                        │
│         │         ├─ ensure_embedded_data()  … zstd 展開      │
│         │         └─ load_helper_module()   … helper 読込     │
│         └─ PyList_Insert(sys.path_hooks, 0, embeddedimporter)│
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  import 時                                                   │
│  sys.path に sys.executable が含まれている場合:               │
│    PathFinder → sys.path_hooks を順に試行                     │
│      → EmbeddedImporter(sys.executable) が成功               │
│        → find_spec() で gperf 検索                           │
│          → exec_module() でコンパイル・実行                   │
└─────────────────────────────────────────────────────────────┘
```

### 役割分担

| レイヤー | ファイル | 役割 |
|---|---|---|
| C ブリッジ | [Modules/embeddedimport.c](Modules/embeddedimport.c) | PEP 489 モジュール初期化、zstd 展開、gperf 検索 API、生データ取得 API |
| Python 本体 | [Lib/embeddedimport_helper.py](Lib/embeddedimport_helper.py) | PEP 451 インポーター全ロジック（`EmbeddedImporter` クラス） |
| データ生成 | [SingleBinaryBuild/create_embeddedimporter_data.py](SingleBinaryBuild/create_embeddedimporter_data.py) | ビルド時にソース収集・圧縮・gperf 入力ファイル生成 |
| 生成コード | `Modules/embeddedimport_data.c`（生成物） | gperf 完全ハッシュテーブル + 圧縮データブロブ |
| 初期化 | [Python/import.c](Python/import.c) `init_embeddedimport()` | `sys.path_hooks` への登録 |
| モジュール表 | [PC/config.c](PC/config.c) | `_PyImport_Inittab[]` への登録（builtin モジュール） |

---

## ビルドパイプライン

### データ生成の流れ

```
Lib/**/*.py  ──►  get_file_data()  ──►  output_key_file_for_gperf()  ──►  gperf  ──►  Modules/embeddedimport_data.c
  (コメント除去,       (zstd 圧縮,              (完全ハッシュ
   NULL 終端)           gperf キー生成)           C ルックアップテーブル)
```

### 1. データ収集（`get_file_data()`）

[create_embeddedimporter_data.py](SingleBinaryBuild/create_embeddedimporter_data.py) が `Lib/` ディレクトリで以下のファイルを収集します：

- `**/*.py` — すべての Python ソースファイル
- `lib2to3/*.pickle` — Grammar ファイル
- `certifi/cacert.pem` — CA 証明書バンドル
- `werkzeug/debug/shared/*.*` — Werkzeug デバッガリソース

**スキップ対象**:
- `test/` および `*/test/` 配下
- `__pycache__/` 配下
- `lib2to3/tests/`, `distutils/tests/`, `idlelib/idle_test/`
- `ubuntu.ttf`

**処理**:
- `.py` ファイル: `tokenize` モジュールでコメントを除去し、行構造は保持
- 全ファイル: バイナリデータの末尾に NULL バイト（`\0`）を付加

### 2. 圧縮と gperf 入力生成（`output_key_file_for_gperf()`）

1. 全ファイルのデータを連結
2. zstd 最高圧縮レベルで圧縮
3. gperf キーファイル（`Modules/embeddedimporter_gperf_keyfile.txt`）を生成:
   - `%{ ... %}` プリアンブル: 圧縮データブロブの C 配列定義、サイズ定数
   - `struct file_offset { filename, offset, size }` 型定義
   - `%%` セクション: 各ファイルの `filename,offset,size` エントリ

### 3. gperf 実行

```
gperf -L ANSI-C -t -N embeddedimporter_find_entry -K filename \
      --output-file=Modules/embeddedimport_data.c \
      Modules/embeddedimporter_gperf_keyfile.txt
```

生成される `Modules/embeddedimport_data.c` には以下が含まれます：

| シンボル | 型 | 内容 |
|---|---|---|
| `embeddedimporter_raw_data_size` | `const size_t` | 展開後のデータサイズ |
| `embeddedimporter_raw_data_compressed[]` | `const unsigned char[]` | zstd 圧縮データ |
| `embeddedimporter_raw_data_compressed_size` | `const size_t` | 圧縮データサイズ |
| `embeddedimporter_find_entry(str, len)` | 関数 | ファイル名 → `struct file_offset*` の O(1) 検索 |

---

## C モジュール: `embeddedimport.c`

### モジュール定義（PEP 489 マルチフェーズ初期化）

```c
static PyModuleDef_Slot embeddedimport_slots[] = {
    {Py_mod_multiple_interpreters, Py_MOD_PER_INTERPRETER_GIL_SUPPORTED},
    {Py_mod_exec, embeddedimport_exec},
    {0, NULL}
};

static struct PyModuleDef embeddedimportmodule = {
    PyModuleDef_HEAD_INIT,
    "embeddedimport",
    "Embedded importer helper module.",
    0,                          // m_size = 0（モジュール単位の状態なし）
    embeddedimport_methods,
    embeddedimport_slots,
    NULL, NULL, NULL
};

PyMODINIT_FUNC
PyInit_embeddedimport(void)
{
    return PyModuleDef_Init(&embeddedimportmodule);
}
```

- `PyModuleDef_Init()` を返す（PEP 489 マルチフェーズ初期化）
- `Py_mod_multiple_interpreters` により **サブインタプリタ対応**
- `Py_mod_exec` スロットで `embeddedimport_exec()` が呼ばれる

### `embeddedimport_exec()` — モジュール実行時コールバック

1. `ensure_embedded_data()` — zstd 圧縮データを展開（初回のみ、プロセスグローバル）
2. `load_helper_module()` — 展開済みデータから `embeddedimport_helper.py` をコンパイル・実行
3. helper モジュールから `EmbeddedImporter` クラスを取得し、`embeddedimporter` 属性として公開

### グローバルデータ管理

```c
static int embedded_data_initialized = 0;
static unsigned char *embedded_raw_data = NULL;
```

- `ensure_embedded_data()` は初回のみ `ZSTD_decompress()` で展開
- 展開済みデータはプロセスグローバルで保持（複数インタプリタで共有）
- `embedded_data_initialized` フラグで二重展開を防止

### `load_helper_module()` — ヘルパーモジュールのブートストラップ

1. gperf テーブルで `"embeddedimport_helper.py"` のエントリを検索
2. 展開済みデータから該当部分を取得
3. `Py_CompileStringObject()` でコンパイル（`flags=NULL`, `optimize=-1`）
4. `PyImport_ExecCodeModuleObject()` でモジュールとして実行
5. 生成されたモジュールオブジェクトを返す

### 公開 API（C → Python）

`embeddedimport` モジュールが Python 側に公開する 3 つの関数：

| 関数 | シグネチャ | 説明 |
|---|---|---|
| `_find_entry(filename)` | `str → (offset, size) \| None` | gperf テーブルでファイルを検索 |
| `_find_entry_in_resource(filename)` | `str → (offset, size) \| None` | Windows リソースでファイルを検索（現在は常に `None`） |
| `_get_data(offset, size, use_resource=False)` | `int, int, bool → bytes` | 展開済みデータからバイト列を取得 |

### Windows リソース対応（`Py_BUILD_RESOURCE_EMBEDDED_MODULE`）

`#ifdef Py_BUILD_RESOURCE_EMBEDDED_MODULE` で囲まれたコードブロックが存在しますが、現在は **`#error Not Implemented.`** が設定されており、ビルド不可の状態です。

有効化された場合の想定動作：
1. `FindResource(NULL, MAKEINTRESOURCE(200), RT_RCDATA)` でリソースを取得
2. リソースデータのバイナリ構造を解析：
   ```
   uint32_t compressed_size
   uint32_t uncompressed_size
   uint32_t file_count
   uint32_t file_offset[file_count]
   unsigned char compressed_file_data[compressed_size]
   char file_name[]  // NULL 区切り
   ```
3. 展開して `embedded_index_resource` 辞書に `{filename: (offset, size)}` を登録

---

## Python ヘルパー: `embeddedimport_helper.py`

### クラス: `EmbeddedImporter`

`_bootstrap_external._LoaderBasics` を継承した PEP 451 path-hook インポーター。

#### `__init__(self, path: str)`

path-hook として `sys.path_hooks` から呼ばれます。

1. `embeddedimport` C モジュールを遅延ロード（`_load_c_extension()`）
2. `path` を `sys.executable` と比較（`os.path.normcase` + `os.path.normpath` で正規化）
3. 一致: `self.prefix = ""`（ルートインポーター）
4. サブパス: `self.prefix = "relative/path/"` を算出
5. 不一致: `ImportError` を送出（他の path-hook に委譲）

#### `find_spec(self, fullname, target=None)`

1. `fullname` をモジュールパス（`"."` → `"/"`）に変換
2. `self.prefix` とプレフィックスが一致するか確認
3. `_find_entry()` で検索（後述）
4. `.py` ファイルが見つかった場合: `spec_from_loader()` で `ModuleSpec` を返す
5. ソースなしディレクトリが見つかった場合: 名前空間パッケージ用 `ModuleSpec` を返す
6. 見つからない場合: `None` を返す

#### `exec_module(self, module)`

1. `get_code()` でコードオブジェクトを取得
2. `__loader__`, `__file__`, `__path__` を設定
3. `_bootstrap_external._fix_up_module()` を呼び出し
4. `exec(code, module.__dict__)` でモジュールを実行

#### `create_module(self, spec)`

常に `None` を返します（標準のモジュール生成に委譲）。

### 補助 API（Loader Protocol）

| メソッド | 説明 |
|---|---|
| `get_code(fullname)` | ソースを取得 → `compile()` でコードオブジェクトを返す |
| `get_source(fullname)` | ソースを `bytes.decode()` で UTF-8 文字列として返す |
| `get_filename(fullname)` | `sys.executable + "/" + embedded_path` 形式のパスを返す |
| `get_data(pathname)` | OS パスから埋め込みデータを `bytes` で返す |

### 検索ロジック（`_find_entry` / `_iter_candidates`）

`fullname` に対して以下の候補を順に検索します：

| 優先度 | 候補パス | is_package |
|---|---|---|
| 1 | `module/path/__init__.py` | `True` |
| 2 | `module/path.py` | `False` |
| 3 | `module/path`（名前空間パッケージ） | `True` |

各候補について、まず `_find_entry_in_resource()`（リソースデータ）を検索し、次に `_find_entry()`（静的データ）を検索します。

### ユーティリティ関数

| 関数 | 説明 |
|---|---|
| `_normalize_line_endings(source)` | `\r\n` / `\r` を `\n` に統一 |
| `_compile_source(pathname, source)` | 改行統一後に `compile()` を実行 |
| `_to_module_path(fullname)` | `"."` → `"/"` 変換 |
| `_normalize_path(path)` | `os.path.normcase(os.path.normpath(path))` |
| `_to_os_path(executable, embedded_path)` | `os.path.join(exe, path)` で OS パス構築 |

---

## 初期化フロー

### Python 起動時の処理順序

[Python/import.c](Python/import.c) の `_PyImport_InitExternal()` 内で、以下の順に初期化されます：

```c
PyStatus _PyImport_InitExternal(PyThreadState *tstate) {
    // 1. 標準 importlib 初期化
    init_importlib_external(tstate->interp);

    // 2. zipimport フック登録
    init_zipimport(tstate, verbose);

    // 3. embeddedimport フック登録  ← ★
    init_embeddedimport(tstate, verbose);
}
```

### `init_embeddedimport()` の処理

1. `sys.path_hooks` を取得
2. `embeddedimport.embeddedimporter` を import（ここで C モジュールの `embeddedimport_exec` が実行される）
3. `PyList_Insert(path_hooks, 0, embeddedimporter)` — **先頭に挿入**（最高優先度）
4. verbose モード時はステータスを stderr に出力

### パスフック解決の流れ

`sys.path` の各エントリに対して `sys.path_hooks` が順に試行されます：

1. `EmbeddedImporter(path)` — path が `sys.executable` に一致すれば成功
2. `zipimporter(path)` — `.zip` パスなら成功
3. `FileFinder.path_hook(path)` — ファイルシステム上のディレクトリなら成功

`sys.path` に `sys.executable` が含まれている場合、`EmbeddedImporter` が最初にマッチし、埋め込みデータからインポートが行われます。

---

## ビルドの組み込み

### PC/config.c

`embeddedimport` は builtin モジュールとして `_PyImport_Inittab[]` に登録されています：

```c
extern PyObject* PyInit_embeddedimport(void);

struct _inittab _PyImport_Inittab[] = {
    ...
    {"embeddedimport", PyInit_embeddedimport},
    ...
};
```

### Visual Studio プロジェクト

`pythoncore.vcxproj` に以下の 2 ファイルがコンパイル対象として含まれています：

- `Modules/embeddedimport.c` — C ブリッジモジュール
- `Modules/embeddedimport_data.c` — gperf 生成の完全ハッシュテーブル + 圧縮データ

リンク時に zstd ライブラリ（`libzstd_static.lib`）が必要です。

---

## Python 3.13 の現状との差分と修正方針（zipimport を基準に整理）

### 1. Builtin 登録（PC/config.c）

**現状**: [PC/config.c](PC/config.c) に `embeddedimport` の登録がありません。

**修正方針**:
- `PyInit_embeddedimport()` の extern 宣言を追加
- `_PyImport_Inittab` に `{"embeddedimport", PyInit_embeddedimport}` を追加

**目的**:
`embeddedimport` モジュールを組み込みモジュールとして登録し、ファイルシステム無しで import 可能にする。

### 2. `sys.path_hooks` 挿入（Python/import.c）

**現状**: [Python/import.c](Python/import.c) に EmbeddedImporter 追加処理は存在しません。

**修正方針**:
- `_PyImport_InitExternal()` 内の `init_zipimport()` 呼び出し直後に EmbeddedImporter 初期化関数を追加
- `embeddedimport` モジュールを import
- `embeddedimporter` クラスを取得
- `sys.path_hooks` の **先頭（index 0）** に挿入: `PyList_Insert(path_hooks, 0, embeddedimporter)`

**zipimport との整合性**:
- `init_zipimport()` は `PyList_Insert(path_hooks, 0, zipimporter)` で zipimporter を先頭に挿入します
- EmbeddedImporter を**その後に index 0 へ挿入**することで、最終的な検索順は `embeddedimporter` → `zipimporter` → `FileFinder` → ... となります
- これにより、実行ファイル内のモジュールが最優先で検索されます

### 3. 初期化タイミング（Python/pylifecycle.c）

**現状**: [Python/pylifecycle.c](Python/pylifecycle.c#L1205-L1235) では `_PyImport_InitExternal()` を呼ぶのみ。

**修正方針**:
- `_PyImport_InitExternal()` の内部で EmbeddedImporter を登録する（または呼び出し直後に追加）
- zipimport の初期化が終わっていることが必須

### 4. 内部ヘッダ（Include/internal/pycore_pylifecycle.h）

**現状**: `_PyImportEmbedded_Init()` の宣言は存在しない。

**修正方針**:
- 追加する場合は宣言を `pycore_pylifecycle.h` に入れる

### 5. Modules/embeddedimport_data.c

**生成方法**: [SingleBinaryBuild/create_embeddedimporter_data.py](SingleBinaryBuild/create_embeddedimporter_data.py) によって自動生成

**内容**:
```c
char embeddedimporter_filename[];
const size_t embeddedimporter_raw_data_size;
const unsigned char embeddedimporter_raw_data_compressed[];
const size_t embeddedimporter_raw_data_compressed_size;
const size_t embeddedimporter_data_offset[];
```

**目的**:
埋め込むファイルの実データを提供します。ビルド時に生成され、実行ファイルにリンクされます。

### 6. SingleBinaryBuild/create_embeddedimporter_data.py

**機能**:
1. `Lib/` ディレクトリ配下の `.py` ファイルを再帰的に収集
2. テストファイル、`__pycache__` などをスキップ
3. Python ファイルのコメントを削除して容量削減
4. `.pickle` ファイル（lib2to3 用）や特定のリソースファイルも含める
5. すべてのデータを zlib 圧縮
6. C ソースコード形式で `Modules/embeddedimport_data.c` に出力

**主要処理**:
```python
def get_file_data():
    # ファイル収集とフィルタリング
    # コメント削除処理
    # バイナリデータの結合

def output_list(file_list):
    # C言語のデータ配列として出力
    # 圧縮とオフセットテーブルの生成
```

### 7. ビルドシステム（SingleBinaryBuild）

**必要な変更**:
- `Modules/embeddedimport.c` をビルド対象に追加
- `Modules/embeddedimport_data.c` をビルド対象に追加
- zlib ライブラリとのリンク
- ビルド前に `create_embeddedimporter_data.py` を実行
- （オプション）リソース埋め込み用のビルドステップ

### 8. Windows リソース対応（オプション）

**条件**: `Py_BUILD_RESOURCE_EMBEDDED_MODULE` が定義されている場合

**追加処理**:
- Windows リソーススクリプト（.rc ファイル）に埋め込みデータを追加
- リソース ID `200` (`USER_SOURCE_ID`) でバイナリデータを埋め込み
- 実行時に `FindResource()`, `LoadResource()` でアクセス

**利点**:
- ビルド後にリソースを追加・変更可能
- 動的なライブラリの追加が容易

---

## まとめ（Python 3.13 の要点）

EmbeddedImporter は、以下の技術を組み合わせて実現されています：

1. **データ埋め込み**: ビルド時に全ライブラリを C 配列として埋め込み
2. **圧縮**: zlib による効率的な容量削減
3. **Import Protocol**: Python 3.13 の `sys.path_hooks` / `zipimporter` と整合する必要がある
4. **最適化**: グローバルキャッシュによる複数インスタンス間でのデータ共有
5. **柔軟性**: コンパイル時データとリソースデータの両対応

**重要ポイント**: 3.13 では `zipimporter` が `init_zipimport()` 内で `sys.path_hooks` に挿入されるため、EmbeddedImporter は **zipimport の後に** `sys.path_hooks` の先頭へ入れるのが最も自然です。また、長期的には `find_module/load_module` ではなく **PEP 451 (`find_spec/create_module/exec_module`)** を実装して zipimporter と同等のインターフェースに寄せるのが妥当です。

この仕組みにより、外部ファイルなしで動作する単一バイナリの Python 実行環境を実現しています。
