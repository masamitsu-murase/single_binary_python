# Tcl/Tk 埋め込み実装仕様（設計仕様書）

## 1. 文書目的

本書は、Tcl/Tk スクリプト資産を単一バイナリ実行環境へ埋め込む機能について、設計上の責務・構成・インターフェース・制約を定義する。

## 2. 適用範囲

- 対象機能: Tcl/Tk スクリプトの埋め込み、展開、VFS 公開、`_tkinter` 連携
- 対象外: `embeddedimport`（Python 標準ライブラリ埋め込み）、Tk GUI API 仕様そのもの

## 3. 背景・概要

本機能は、`embeddedimport` とは独立した仕組みとして、Tcl/Tk のスクリプト群（`externals/tcltk-8.6.15.0/amd64/lib/tcl8.6`、`externals/tcltk-8.6.15.0/amd64/lib/tk8.6`）を静的ライブラリ内に埋め込み、実行時に Tcl の仮想ファイルシステム（VFS）として公開する。

主要構成要素は以下のとおり。

- データ生成: `SingleBinaryBuild/create_tcl_embeddedfilesystem_data.py`
- VFS 実装: `Modules/_tkinter_tclEmbeddedFilesystem.c`
- 生成データ: `Modules/_tkinter_tclEmbeddedFilesystemData.c`
- Python 連携: `Modules/_tkinter.c`
- ビルド連携: `SingleBinaryBuild/_tkinter.vcxproj`

## 4. 要件

### 4.1 機能要件

1. `tcl8.6` および `tk8.6` 配下のスクリプトを単一バイナリへ同梱できること。
2. 実行時に `embeddedfs:/` として Tcl から参照可能であること。
3. `Tcl_Init()` が `embeddedfs:/tcl8.6` 上の `init.tcl` を解決できること。
4. `_tkinter` 初期化時に VFS 登録が完了していること。

### 4.2 非機能要件

1. 埋め込みデータは圧縮形式（zstd）で保持すること。
2. 実行時展開は 1 回のみとし、再展開を回避すること。
3. VFS は読み取り専用であること。

## 5. アーキテクチャ

### 5.1 モジュール分割

- 生成層: `create_tcl_embeddedfilesystem_data.py`
- データ層: `_tkinter_tclEmbeddedFilesystemData.c`
- VFS 層: `_tkinter_tclEmbeddedFilesystem.c`
- 連携層: `_tkinter.c`
- ビルド層: `_tkinter.vcxproj`

### 5.2 データフロー

1. ビルド時、生成スクリプトが Tcl/Tk 資産を収集・圧縮し、C ソースを生成する。
2. 生成データと VFS 実装が `_tkinter` ビルド成果物へリンクされる。
3. 実行時、`PyInit__tkinter` で VFS を登録し、`tcl_library` を `embeddedfs:/tcl8.6` に誘導する。
4. `Tcl_Init()` / `Tk_Init()` が VFS 上のスクリプトを参照する。

## 6. データ生成仕様

### 6.1 入力

- ベースディレクトリ: `externals/tcltk-8.6.15.0/amd64/lib`
- 収集対象:
  - `tcl8.6/**/*`（ファイル）
  - `tk8.6/**/*`（ファイル）
  - 親ディレクトリエントリ

### 6.2 変換処理

1. ファイル内容を連続バイト列へ連結
2. zstd 圧縮
3. C ソース生成

### 6.3 出力

出力先: `Modules/_tkinter_tclEmbeddedFilesystemData.c`

主要シンボル:

- `gCompressedData[]`
- `gUncompressedData[]`
- `gEmbeddedFileInfo[]`
- `EmbeddedFileInfoDataInitialize()`
- `gEmbeddedFileInfoCount`

## 7. VFS 実装仕様

対象: `Modules/_tkinter_tclEmbeddedFilesystem.c`

### 7.1 データモデル

- `EmbeddedFileInfo`
  - `name`: VFS 内パス
  - `type`: `EMBEDDED_FILE_INFO_TYPE_DIRECTORY` / `EMBEDDED_FILE_INFO_TYPE_FILE`
  - `file_content`: 展開済みデータへのポインタ
  - `file_size`: バイト長

### 7.2 パス解決

- `EmbeddedPathInFilesystem()` で `embeddedfs:/` プレフィックスを判定
- `FindFileInfo()` でプレフィックス除去後の相対パスを検索

### 7.3 チャネル I/O

- `EmbeddedOpenFileChannel()` は読み取り専用チャネルを生成
- `EmbeddedInput()` はメモリバッファから読み出し
- `EmbeddedOutput()` は書き込みを拒否（`EACCES`）

### 7.4 メタ情報

- `EmbeddedAccess()`:
  - 読み取り/存在確認を許可
  - 書き込み系を拒否
- `EmbeddedStat()`:
  - `S_IFDIR` または `S_IFREG` を返却
- `EmbeddedListVolumes()`:
  - `embeddedfs:/` を列挙

### 7.5 登録

- `TclEmbeddedFilesystemRegister()`
  1. `EmbeddedFileInfoDataInitialize()` 実行
  2. `Tcl_FSRegister(NULL, &embeddedFilesystem)` 実行

## 8. `_tkinter` 連携仕様

対象: `Modules/_tkinter.c`

1. `TclEmbeddedFilesystemRegister()` を宣言
2. モジュール初期化で `TclEmbeddedFilesystemRegister()` を呼び出し
3. `_get_tcl_lib_path()` で `embeddedfs:/tcl${TCL_VERSION}` を返却
4. `Tkapp_New()` でインタプリタ変数 `tcl_library` を設定
5. `PyInit__tkinter` で `TCL_LIBRARY` 環境変数を一時設定して `Tcl_FindExecutable()` を実行

期待結果:

- `Tcl_AppInit()`（`Modules/tkappinit.c`）からの `Tcl_Init()` / `Tk_Init()` が埋め込み資産を参照可能となる。

## 9. ビルド統合仕様

### 9.1 生成タイミング

`SingleBinaryBuild/_tkinter.vcxproj` の前処理で `_tkinter` ビルド前に実行する。

- `python SingleBinaryBuild/create_tcl_embeddedfilesystem_data.py <tcltkBaseDir> Modules/_tkinter_tclEmbeddedFilesystemData.c`

### 9.2 コンパイル対象

- `_tkinter.c`
- `_tkinter_tclEmbeddedFilesystem.c`
- `_tkinter_tclEmbeddedFilesystemData.c`

### 9.3 リンク要件

- `tcl86ts.lib`
- `tk86ts.lib`

上記を `_tkinter` のリンク対象に含める。

## 10. 変更箇所一覧（実装成立に必須）

1. 生成スクリプト追加/維持
   - `SingleBinaryBuild/create_tcl_embeddedfilesystem_data.py`
2. VFS 実装追加/維持
   - `Modules/_tkinter_tclEmbeddedFilesystem.c`
3. 生成データのビルド対象化
   - `Modules/_tkinter_tclEmbeddedFilesystemData.c`
4. Python 側初期化連携
   - `Modules/_tkinter.c`
5. ビルド設定統合
   - `SingleBinaryBuild/_tkinter.vcxproj`

## 11. 制約・注意事項

1. VFS は読み取り専用。
2. ファイル検索は線形検索であり、エントリ増加時に探索コストが増加する。
3. 初回登録時にデータを一括展開するため、起動初期のメモリ使用量が増える。
4. `tcl_library` が `embeddedfs:/tcl8.6` を指すことを前提とする。
5. Tk スクリプトは同一 VFS 内の `tk8.6` 配下で提供する。

## 12. 到達目標

外部 `lib/tcl8.6`・`lib/tk8.6` 配置へ依存せず、単一バイナリ構成で Tcl/Tk 初期化を成立させること。
