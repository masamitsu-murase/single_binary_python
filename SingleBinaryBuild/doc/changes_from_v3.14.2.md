# v3.14.2 から現在コードまでの主要差分サマリ

## 概要

本ドキュメントは、tag `v3.14.2` と現在の HEAD の差分を対象に、主要な変更点を整理した要約です。

> 注: すべての変更を列挙したものではありません。主要テーマのみを抽出しています。

---

## 目次

1. [調査対象と規模](#調査対象と規模)
2. [変更の全体像](#変更の全体像)
3. [主要変更 1: EmbeddedImporter 強化](#主要変更-1-embeddedimporter-強化)
4. [主要変更 2: Tcl/Tk の埋め込み対応（_tkinter）](#主要変更-2-tcltk-の埋め込み対応_tkinter)
5. [主要変更 3: 静的リンク前提の初期化・公開シンボル調整](#主要変更-3-静的リンク前提の初期化公開シンボル調整)
6. [主要変更 4: SingleBinaryBuild 側のビルド基盤拡張](#主要変更-4-singlebinarybuild-側のビルド基盤拡張)
7. [補足: 変更量の大半を占める生成物](#補足-変更量の大半を占める生成物)
8. [まとめ](#まとめ)

---

## 調査対象と規模

- 比較範囲: `v3.14.2..HEAD`
- コミット数: 95
- 変更ファイル数: 233
- 差分行数: `286,576 insertions`, `68 deletions`

ディレクトリ単位の傾向（ファイル数ベース）:

- `SingleBinaryBuild/`: 64.4%（150 files）
- `.github_org/`: 15.5%（36 files）
- `Lib/`: 11.6%（27 files）
- `Modules/`: 3.9%（9 files）
- `PC/`: 1.7%（4 files）
- その他（`Include/`, `Python/`, `Tools/`, `.github/`, ルート）: 少量

---

## 変更の全体像

`single_binary_python` ブランチでは、v3.14.2 から以下の方向で実装が進んでいます。

1. **単一バイナリ import 基盤の実用化**
   - `embeddedimport` の実装拡張（zstd、gperf、サブインタプリタ対応）
2. **GUI 同梱対応の前進**
   - `_tkinter` と Tcl/Tk データの埋め込み対応
3. **静的リンク構成の拡張**
   - 組み込みモジュール登録、Windows 向け公開シンボル周辺の整備
4. **ビルド運用の実装フェーズ化**
   - `SingleBinaryBuild/` 一式の `.vcxproj` / `.props` / 生成スクリプトの拡充

---

## 主要変更 1: EmbeddedImporter 強化

### 変更概要

- `Modules/embeddedimport.c` を中心に、埋め込み import 機構を段階的に強化
- `Python/import.c` で `sys.path_hooks` へ `embeddedimporter` を追加
- `Modules/getpath.py` で `sys.path` に実行ファイル自身を追加（埋め込みデータ探索の起点）
- `Lib/embeddedimport_helper.py` の整備

### v3.14.2 からの進展ポイント

- **zstd 圧縮運用**への移行
- **gperf 利用**でキー検索を高速化
- **サブインタプリタ対応**の導入
- リファクタリングによる可読性改善

---

## 主要変更 2: Tcl/Tk の埋め込み対応（_tkinter）

### 変更概要

- `_tkinter` が埋め込み Tcl/Tk ファイルシステムを扱える構成へ拡張
- 追加/更新の中心:
  - `Modules/_tkinter.c`
  - `Modules/_tkinter_tclEmbeddedFilesystem.c`
  - `Modules/_tkinter_tclEmbeddedFilesystemData.c`
  - `Modules/_tkinter_tclEmbeddedFilesystemData.h`

### 実装上のポイント

- `WITH_EMBEDDED_TCLTK_FILESYSTEM` 条件下で、
  - Tcl/Tk 埋め込みファイルシステム登録
  - `TCL_LIBRARY` 解決先の埋め込みパス化
- メモリ割り当て・パス処理・並び順などの修正コミットを継続的に適用

### 意味合い

単一バイナリで GUI 系標準モジュールを扱うための主要ギャップ（Tcl/Tk 依存）に対して、実装ベースで対応が進んだ段階です。

---

## 主要変更 3: 静的リンク前提の初期化・公開シンボル調整

### 変更概要

- `PC/config.c` に静的リンクされた拡張モジュール群の `inittab` 登録を追加
  - `_asyncio`, `_bz2`, `_ctypes`, `_decimal`, `_elementtree`, `_hashlib`, `_lzma`, `_multiprocessing`, `_socket`, `_sqlite3`, `_ssl`, `_tkinter`, `_zstd`, `pyexpat`, `select`, `unicodedata`, `winsound` など
- `embeddedimport` も組み込みモジュールとして登録
- Windows 固有のシンボル公開/参照に関する条件式を `Py_SINGLE_BINARY_BUILD` へ対応
  - `Include/exports.h`
  - `Python/sysmodule.c`
  - `PC/dl_nt.c`

### 意味合い

DLL 分離前提ではなく、**実行ファイルへ集約する前提**で初期化経路とシンボルの扱いを合わせ込む変更です。

---

## 主要変更 4: SingleBinaryBuild 側のビルド基盤拡張

### 変更概要

`SingleBinaryBuild/` 配下で大規模に更新（150 ファイル変更）。特に以下が中核です。

- `.vcxproj` / `.filters` の広範な更新
- `pythoncore.vcxproj`, `python.vcxproj`, `pythonw.vcxproj` の静的リンク前提調整
- `pymodule_static.props`, `python_modules_link.props`, `pyproject.props`, `python.props` などの調整
- 外部依存ビルドスクリプト拡張
  - `prepare_ssl.bat` / `prepare_ssl.py`
  - `prepare_libffi.bat`
  - `prepare_tcltk.bat`
- データ生成スクリプト追加・強化
  - `create_embeddedimporter_data.py`
  - `create_tcl_embeddedfilesystem_data.py`

### 運用面の変化

- OpenSSL/libffi/Tcl/Tk の静的リンク前提を明示化
- `_tkinter` を含む構成でのビルド再現性改善
- リソース（アイコン等）関連の調整（`tk_base.rc` 追加、重複対策コミット）

---

## 補足: 変更量の大半を占める生成物

差分行数の大部分は、以下の**生成データ**が占めます。

- `Modules/embeddedimport_data.c`（約 10.3 万行追加）
- `Modules/embeddedimporter_gperf_keyfile.txt`（約 10.2 万行追加）
- `Modules/_tkinter_tclEmbeddedFilesystemData.c`（約 6.0 万行追加）

このため、見かけ上の差分量は非常に大きいですが、実装上の主要テーマは前章までの 4 点に集約できます。

---

## まとめ

v3.14.2 以降の差分は、単なるビルドスクリプト調整ではなく、以下の 2 軸で進展しています。

1. **import/runtime 側の成立性向上**
   - EmbeddedImporter の実用強化
   - `inittab` / `sys.path_hooks` / Windows シンボル周辺の整備
2. **配布形態としての完成度向上**
   - Tcl/Tk 埋め込み対応の追加
   - 外部依存を含む静的リンクビルド運用の実装

結果として、単一バイナリ Python の実運用に必要な要素（CLI + 標準拡張 + GUI 依存）を段階的に取り込んだ差分構成になっています。
