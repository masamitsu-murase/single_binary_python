# EmbeddedImporter 実装の詳細（Python 3.13 対応版）

## 概要

EmbeddedImporter は、Python の標準ライブラリや外部ライブラリのソースコードを実行ファイル内に埋め込み、単一の実行ファイルで Python を動作させるための機能です。Python 3.13 の importlib 実装（`init_importlib_external` + `init_zipimport`）に合わせて、パスフックの挿入位置とプロトコル（PEP 451）を意識した設計に更新する必要があります。

### 主な特徴

- **単一バイナリ化**: すべてのライブラリを実行ファイル内に埋め込む
- **zlib 圧縮**: ファイルデータを圧縮して埋め込むことでファイルサイズを削減
- **Python Import Protocol 準拠**: 3.13 の importlib フローと整合する必要がある
- **2つのデータソース対応**:
  - コンパイル時に埋め込まれた静的データ
  - Windows リソースとして追加された動的データ（`Py_BUILD_RESOURCE_EMBEDDED_MODULE` が定義されている場合）

---

## 動作原理（Python 3.13 の流れに合わせた説明）

### 1. データの埋め込み

ビルド時に以下の手順でライブラリデータを埋め込みます：

1. **データ収集**: [SingleBinaryBuild/create_embeddedimporter_data.py](SingleBinaryBuild/create_embeddedimporter_data.py) が `Lib` ディレクトリ配下の `.py` ファイルや必要なリソースファイルを収集
2. **データ処理**:
   - Python ソースコードからコメントを削除して容量削減
   - すべてのファイルを連結し、ファイル間は NULL バイト（`\0`）で区切り
3. **圧縮**: 連結したデータを zlib で圧縮
4. **C ソース生成**: `Modules/embeddedimport_data.c` に以下のデータを出力：
   - `embeddedimporter_filename[]`: ファイル名のリスト（NULL 区切り）
   - `embeddedimporter_raw_data_compressed[]`: 圧縮されたファイルデータ
   - `embeddedimporter_raw_data_size`: 展開後のサイズ
   - `embeddedimporter_raw_data_compressed_size`: 圧縮後のサイズ
   - `embeddedimporter_data_offset[]`: 各ファイルのデータ開始オフセット

### 2. Import フックの登録（Python 3.13 の `zipimport` に合わせる）

Python 3.13 では、外部インポート初期化が [_PyImport_InitExternal](Python/import.c#L4178-L4211) に集約されています。

1. **`init_importlib_external()` が `sys.path_hooks` と `path_importer_cache` を構築**
   - `importlib._bootstrap_external` により `FileFinder` などが登録される
2. **`init_zipimport()` が `zipimport.zipimporter` を `sys.path_hooks` に挿入**
   - これにより `.zip` パスが優先的に処理される

EmbeddedImporter を **Python 3.13 の流れに合わせて挿入するには**、`init_zipimport()` 後に `embeddedimporter` を `sys.path_hooks` の先頭へ挿入するのが最も自然です。`zipimporter` と同様の path-hook 型として動作させるのが前提になります。

### 3. パスフック呼び出しと zipimport の挙動

`sys.path` の各エントリに対して `sys.path_hooks` が順に呼ばれ、**ハンドルできない場合は ImportError を返す**という契約があります（[_PyImport_GetImporter -> get_path_importer](Python/import.c#L3320-L3396)）。

- `zipimporter` は `.zip` などのパスを受け取った時だけ有効な importer を返し、それ以外は `ImportError` を返す
- EmbeddedImporter も同様に「実行ファイル自身のパス、またはそのサブパスのみを受け付ける」ことで zipimport と共存できる

---

## Modules/embeddedimport.c の内容説明（実装済み）

**注意**: 実装は `embeddedimport.c` + `embeddedimport_helper.py` の分担方式です。C 側はブリッジ、Python 側が PEP 451 本体を担当します。

### 実装方針（embeddedimport.c + embeddedimport_helper.py 併用）

**方針**: 主要ロジックは Python 側で実装し、C 側は軽量なブリッジに徹する。

#### 役割分担

- [Modules/embeddedimport.c](Modules/embeddedimport.c)
   - builtin モジュールのエントリポイント（`PyInit_embeddedimport`）
   - `embeddedimporter` クラスの公開
   - **C 側で必須となる低レベル API** のみ実装
      - 埋め込みデータバッファの取得
      - zlib 展開（必要なら）
      - バイナリデータへの直接アクセス（offset/size）
   - Python 側 helper へ処理委譲するための最小限の関数を提供

- embeddedimport_helper.py
   - **PEP 451 実装の本体**（`find_spec`/`create_module`/`exec_module`）
   - `zipimporter` と整合する補助 API (`get_code`/`get_source`/`get_filename`/`get_data`)
   - パス正規化、prefix 生成、検索順序の実装
   - `importlib._bootstrap`/`importlib._bootstrap_external` の利用

#### C から Python helper への接続方法

- `PyInit_embeddedimport` 内で helper モジュールを import
- helper 内の `EmbeddedImporter` クラスを公開名 `embeddedimporter` として再公開
- C 側はデータ取得 API のみを提供し、**実際の import ロジックは helper が呼び出す**

#### 想定される helper 構成（例）

- `class EmbeddedImporter`
   - `__init__(path)` で path-hook として振る舞う
   - `find_spec` で埋め込み索引を検索
   - `exec_module` で `get_code` を実行し、モジュールを初期化
   - `get_data` などの補助 API を C から提供される関数で実装

#### この方針の利点

- importlib と zipimport の仕様変更に **Python 側で迅速に追従**できる
- C 実装の肥大化を避けられる
- PEP 451 の詳細ロジックを Python で記述でき、可読性が高い

### 実装内容の要点（Python 3.13 の importlib/zipimport と整合させた仕様）

**目標**: `zipimporter` と同等のインターフェース（PEP 451）を持つ path-hook 型 importer を提供し、`sys.path_hooks` から呼ばれる importer として動作させる。

#### 1) クラス構造（`embeddedimporter`）

- `embeddedimporter(path)` は **path-hook として呼ばれる**
- `path` が実行ファイル自身またはそのサブパスであればインスタンスを生成し、それ以外は **ImportError を送出**
- インスタンスは以下の情報を保持
   - `dict`: 埋め込みデータの索引 `{filename: (offset, size)}`
   - `dict_resource`: Windows リソース由来の索引（任意）
   - `prefix`: 実行ファイル内の論理的なパス接頭辞

#### 2) PEP 451 インターフェース（必須）

`zipimporter` と同じく、以下のメソッドを中心に実装する：

- `find_spec(fullname, target=None)`
   - `fullname` に対する埋め込みデータの有無を `dict`/`dict_resource` で確認
   - 見つかれば `ModuleSpec` を返す（`importlib._bootstrap` の `spec_from_loader` を使用）
   - 見つからなければ `None` を返す
   - 名前空間パッケージ対応が必要なら `spec.submodule_search_locations` を設定

- `create_module(spec)`
   - 基本は `None` を返し、標準の module 作成に任せる

- `exec_module(module)`
   - 対象モジュールのソースを取り出し、`Py_CompileStringObject` 相当でコンパイル
   - `PyImport_ExecCodeModuleObject` 相当で実行
   - `__loader__`, `__file__`, `__path__` の設定を行う

#### 3) 互換 API（`zipimporter` と同等の補助）

- `get_code(fullname)`
- `get_source(fullname)`
- `get_filename(fullname)`
- `get_data(pathname)`

これらは `zipimport.py` の実装と同様に **PEP 451 用の補助 API** として提供するのが望ましい。

#### 4) データ検索ロジック（現行設計の引き継ぎ）

検索順は以下とする（パッケージ/モジュール/名前空間の判定用）：

1. `subname/__init__.py`
2. `subname.py`
3. `subname`（名前空間パッケージ判定）

この検索順は `zipimporter` の `_get_module_info` ロジックと整合する。

#### 5) データ展開とキャッシュ

- `embeddedimporter_raw_data_compressed` を初回のみ zlib 展開
- 展開済みデータを **プロセスグローバルで保持**し、複数インスタンスで共有
- Windows リソース版も同様にグローバル共有

#### 6) Windows リソース対応

- `Py_BUILD_RESOURCE_EMBEDDED_MODULE` が有効な場合のみ有効化
- `FindResource/LoadResource/LockResource` で取得したバイナリを解析
- 解析結果を `dict_resource` に反映

#### 7) 3.13 の API 変化への対応点

- 実行ファイルパスは `PyConfig_Get("executable")` で取得
- verbose 判定は `PyConfig_GetInt("verbose", &verbose)`
- `Py_CompileStringObject` の引数増加に対応（`flags`/`optimize`）

---

### 実装構成（擬似コード概要）

```
class embeddedimporter:
      def __init__(self, path):
            validate path vs executable
            prefix = compute
            ensure global data initialized

      def find_spec(self, fullname, target=None):
            if not in embedded index:
                  return None
            return spec_from_loader(fullname, self, is_package=...)

      def exec_module(self, module):
            code = get_code(fullname)
            set __loader__/__file__/__path__
            exec(code, module.__dict__)

      def get_code/get_source/get_data/get_filename(...):
            read from embedded data
```

### データ構造

#### `EmbeddedImporter` 構造体
```c
struct _embeddedimporter {
    PyObject_HEAD
    PyObject *dict;           // コンパイル時埋め込みデータ: {ファイル名: (offset, size)}
    PyObject *dict_resource;  // リソース埋め込みデータ: {ファイル名: (offset, size)}
    PyObject *prefix;         // パス接頭辞（例: "mypackage/"）
};
```

#### 検索順序テーブル
```c
static struct st_embedded_searchorder embedded_searchorder[] = {
    {L"/__init__.py", 1},  // パッケージとして検索
    {L".py", 0},            // モジュールとして検索
    {L"", 0}                // 名前のみで検索
};
```

### 主要関数

#### `construct_filedata(EmbeddedImporter *self)`
コンパイル時に埋め込まれたデータを初期化します。

**処理内容**:
1. 圧縮データを展開（`uncompress()` を使用）
2. ファイル名リストを走査
3. 各ファイルについて (offset, size) のタプルを作成
4. `self->dict` 辞書に登録
5. ファイル名中の `/` を `SEP`（Windows では `\\`）に変換

**重要**: この関数は最初の `EmbeddedImporter` インスタンス作成時のみ実行され、データはグローバルに共有されます。

#### `construct_filedata_from_resource(EmbeddedImporter *self)`
（`Py_BUILD_RESOURCE_EMBEDDED_MODULE` が定義されている場合のみ）

Windows リソースからデータを読み込みます。

**処理内容**:
1. `FindResource()`, `LoadResource()`, `LockResource()` でリソースデータを取得
2. リソースデータの構造を解析:
   ```
   uint32_t compressed_size
   uint32_t uncompressed_size  
   uint32_t file_count
   uint32_t file_offset[file_count]
   unsigned char compressed_file_data[compressed_size]
   char file_name[]  // NULL区切り
   ```
3. データを展開して `self->dict_resource` に登録

#### `embeddedimporter_init(EmbeddedImporter *self, PyObject *args, PyObject *kwds)`
EmbeddedImporter インスタンスの初期化。

**処理内容**:
1. パス引数を受け取る
2. パスが実行ファイル自身またはそのサブパスであることを検証
3. サブパスがある場合は `prefix` を設定（例: `python.exe\mypackage` → `prefix="mypackage\\"`）
4. `.` を `SEP` に変換
5. `construct_filedata()` と `construct_filedata_from_resource()` を呼び出し

#### `find_tuple(EmbeddedImporter *self, const wchar_t *subname, int *is_package, char **raw_data)`
指定されたモジュール名に対応するデータを検索。

**処理内容**:
1. `prefix` と `subname` を結合してフルパスを構築
2. `embedded_searchorder` の順序で検索:
   - `subname/__init__.py`
   - `subname.py`
   - `subname`
3. まず `dict_resource` を検索、次に `dict` を検索
4. 見つかった場合、タプル、is_package フラグ、raw_data ポインタを返す

#### `embeddedimporter_find_module` / `embeddedimporter_load_module`
PEP 302 の `find_module/load_module` は実装しません。**Python 3.13 の `zipimporter` は PEP 451 を実装済み**（`find_spec()`/`get_code()`/`get_data()` など）であり、EmbeddedImporter も **PEP 451 (`find_spec`/`create_module`/`exec_module`)** を実装する前提です。

**PEP 302 vs PEP 451 の違い**:
- PEP 302: `find_module()` が self を返し、`load_module()` でモジュールをロード
- PEP 451: `find_spec()` が ModuleSpec を返し、`exec_module()` で初期化（より効率的で柔軟）

#### その他のメソッド

- **`embeddedimporter_is_package()`**: モジュールがパッケージかどうかを判定
- **`embeddedimporter_get_filename()`**: モジュールの `__file__` 属性の値を返す
- **`embeddedimporter_get_code()`**: コンパイル済みコードオブジェクトを返す
- **`embeddedimporter_get_source()`**: ソースコードを文字列として返す
- **`embeddedimporter_get_data()`**: 任意のファイルデータを取得（画像ファイルなど）

### Python 3.13 API 差分の反映点（現状コードの注意）

- `Py_GetProgramFullPath()` は 3.13 では非推奨なため、`PyConfig_Get("executable")` を使って実行ファイルパスを取得している
- `Py_VerboseFlag` は非推奨なため、`PyConfig_GetInt("verbose", &verbose)` を利用して詳細ログ判定を行っている
- `Py_CompileStringObject()` は 3.13 で引数が増えているため、`flags` と `optimize` 引数（`NULL, -1`）を渡す形に更新されている

### モジュール初期化

#### `PyInit_embeddedimport()`
モジュールの初期化関数。

**処理内容**:
1. `EmbeddedImporter_Type` を準備
2. `embedded_searchorder[0].suffix[0]` に `SEP` を設定
3. モジュールを作成
4. `EmbeddedImportError` 例外クラスを作成（`ImportError` のサブクラス）
5. `embeddedimporter` クラスをモジュールに追加

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
