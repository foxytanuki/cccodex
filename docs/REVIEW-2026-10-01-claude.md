# cccodex レビュー（更新前の現行ソース）

## 前提
- **読んだファイル:** `plugins/codex` 配下の全ファイル（agents、commands、hooks、skills、plugin.json）、`.claude-plugin/marketplace.json`、README.md、CHANGELOG.md、docs/BENCHMARK.md、benchmarks/run-benchmark.sh。
- **実行していないこと:** git・codex・claude は一度も実行していません。未コミット差分があるかも確認できていません（reflog には clone 時点の 9261cda しかありません）。
  - したがって、以下はすべて**現行ソースに元からある問題**です。今回の更新で入った欠陥は、まだ差分がないので存在しません。
- **ラベル:** 【事実】はソースで確認したことです。【要検証】は CLI の挙動について私の知識に基づく前提で、0.159.2 / 2.1.285 では確認していません。

## 要約
- **最優先:**
  - H1: 監査の判定材料が `git status` の差分だけなので、ユーザーの作業中変更（WIP）が上書きされても検出できない。
  - H2: 長時間の Codex 実行を監視・停止する手順が、同期実行＋タイムアウトの下では実行できない。
  - H3: fallback が誤って発動し、実行ログを上書きして証拠を消す。モデルが拒否されても同じモデルで再試行する。
- **次に重要:**
  - M1: テンプレートが結果ファイルのパスと thread_id を出力しない。
  - M2: SubagentStop フックの出力がモデルに届いていない可能性が高い。
- **fable-harness:** 他のファイルから依存されていないので、削除自体は安全です。

---

## 指摘（重要度順）

### 高

**H1. 範囲監査が `git status` のパス集合差分だけで、ユーザー WIP の上書きを検出できない**
- **根拠【事実】:**
  - fixer.md:92 は status-before と status-after の差分から「新たに変更・作成されたパス」だけを見る。
  - subagent-scope-audit.py:24-35, 112-113 もパス集合の差だけを見る。
  - スナップショットは fixer.md:44 の `[ -f "$f" ] || continue` で通常ファイル以外を読み飛ばす。
- **発生条件:**
  - (a) 開始時点ですでに ` M` のファイル（ユーザー WIP）を、Codex が範囲外でさらに編集する。status の行は前後で同じなので検出されない。
  - (b) ` M` のファイルが ` D` になる（削除される）。パスが同じなので、フックは検出しない。
  - (c) 未追跡ディレクトリ。既定の porcelain 出力は `?? dir/` にまとめるため、`[ -f dir/ ]` が偽になり、中身が一切スナップショットされない。中のファイルが変わっても status に出ない。逆に、in-scope の新規ファイルを新しいディレクトリに作ると scope と一致せず、誤警告になる。
  - (d) 未追跡ファイルが削除されても、step 6 の文言（「新たに変更・作成」）の対象外。
- **影響:** このプラグインが最優先で守ると宣言している「タスク開始時点のツリー」が失われても、fixer もフックも気付きません。スナップショットは取っても使われません。
- **修正案:**
  - fixer の step 2・step 6 とフックの status 取得を、すべて `--porcelain=v1 -z --untracked-files=all` に統一する。
  - 開始時点の dirty・未追跡・scope の各パスについて、存在有無・種別・sha256 を記録するマニフェストを作り、監査は内容ハッシュで比較する（status の差分は補助扱い）。
  - 監査は Codex を 1 回実行するたびに行う（step 4、step 5 の再試行、step 8 の後）。step 7 の検証コマンドの後にも行う。
  - 大きな未追跡ファイルはハッシュだけ記録し、上限を超えたら警告する。

**H2. 実行制御：同期実行中の Codex を監視も停止もできず、途中で止まったツリーに対して再実行が走る**
- **根拠【事実】:**
  - fixer.md:70-86 は Codex を前景で同期実行する。
  - step 5（fixer.md:91）は「$EVT が 3 分伸びなければ kill して再試行」とするが、PID を記録していない。実行中は同じ Bash 呼び出しがブロックしているので、観測する手段がない。
  - fixer の tools は `Read, Bash, Grep, Glob` だけ（fixer.md:5）。
  - oracle.md:44 は max effort では「約 10 分の無音は正常」としており、fixer の 3 分と矛盾する。
- **【要検証】:** Bash ツールは既定 2 分・上限 10 分でタイムアウトするという認識です。2.1.285 でタイムアウト時に kill されるのか自動でバックグラウンドに回るのか、またバックグラウンド出力を取得するツールの名前を確認してください。
- **発生条件:** max effort の実行が、タイムアウト指定なしで 2 分、または指定ありでも 10 分を超える。あるいは思考中にイベントが 3 分出ない。
- **影響:**
  - 編集の途中で Codex が止められる、または正常な実行が kill される。
  - 部分的な変更が残ったまま「fresh codex exec」が走り、その間に監査はない。
  - 停止を即興（例: `pkill codex`）すると、並列で動いている他エージェントの Codex も巻き込む。
- **修正案:**
  - Codex を `setsid` などで切り離して起動する。実行ディレクトリ・PID・PGID を必ず出力し、以後は `kill -0` と `wc -c "$EVT"` でポーリングする。停止は記録した PGID だけに対して行う。
  - `run_in_background` を使う場合は、出力取得・停止用のツールを `tools:` に追加する。
  - 同期実行を残すなら、Bash の `timeout` を明示し、その内側で `timeout --kill-after` を使って予算を管理する。
  - ストールの閾値を oracle と揃える。kill や失敗の後は、再試行の前に必ず監査する。

**H3. モデル／effort の fallback と再委譲が過剰・不正確で、証拠も消す**
- **根拠【事実】:**
  - 判定は fixer.md:76 と oracle.md:30 の `grep -qiE '...|effort' "$EVT" "$ERR"`。`$EVT` は `--json` の全イベント（エージェント出力やコマンド出力を含む）。
  - 再実行は同じ `$EVT` / `$ERR` / `$OUT` に `>` で上書きする（fixer.md:77-82）。
  - モデル拒否のパターンに当たっても、再試行は同じ `-m gpt-5.6-sol`（fixer.md:71,78、oracle.md:25,32）。
  - resume は `-m` なしで、effort は `max` 固定（fixer.md:106-109）。
  - step 8 の後に step 6 の再監査の指示がない。
- **発生条件:**
  - 1 回目が作業途中で非 0 終了する（利用上限、ストリーム切断、コンテキスト超過など）。このリポジトリ自体を編集する場合、Codex が agents/*.md や README を読めば、非 0 終了時にこの grep は確実にヒットする。
  - gpt-5.6-sol が使えない。`service_tier="fast"` が拒否された場合も `invalid_request_error` に当たり、同じ条件で再試行される可能性がある。
  - effort の fallback が起きた後に step 8 を実行する。
- **影響:**
  - 部分的に変更済みのツリーに対して、監査なしで 2 回目の書き込み実行が走る。
  - 1 回目の `$EVT` が消え、step 6 の帰属確認の根拠がなくなる。どの分岐が走ったかも出力されないので、「fallback を使ったか」を正しく報告できない。
  - resume は max が通らない環境では毎回失敗する。【要検証】resume 時にモデルが復元されない場合は、config.toml の既定モデルで修正ターンが走る。
  - step 4、5、8 を合わせると、最大 5 回前後の書き込み実行になり得る。そのうち一部は監査されない。
- **修正案:**
  - 再試行は次の 2 条件をどちらも満たす場合だけにする。
    - JSONL を python3 でパースし、`error` / `turn.failed` のメッセージが 0.159.2 で実測した拒否文言に一致する。
    - `command_execution` / `file_change` のイベントが 0 件。
  - 再試行の出力は別ファイルにし、どの分岐が走ったかを echo する。
  - モデル拒否と effort 拒否を分けて扱う。モデル拒否なら即座に失敗報告するか、`-m` を外して config の既定モデルを使うかを方針として明記する。
  - resume には、実際に使ったモデルと effort を渡す。
  - 1 タスクあたりの書き込み実行回数に全体の上限（例: 初回＋修正 1 回）を設け、実行ごとに監査する。
  - モデル名は 1 箇所（例: 環境変数とその既定値）にまとめる。

### 中

**M1. テンプレートが OUT / EVT / ERR / THREAD_ID を出力せず、失敗しても終了コード 0 で返る**
- **根拠【事実】:**
  - fixer.md:55 は「シェル変数は Bash 呼び出しをまたいで残らない」と明記している。
  - それなのに step 4 のブロック（fixer.md:58-89）は、成功時に何も出力しない。
  - 最終行が代入（:88）なので、途中で `false` を通っても終了コードは 0。
  - step 8（:106-111）は未定義の `$THREAD_ID` と `$TIGHTER_FOLLOWUP` を使う。
  - oracle.md:21-41 も `$OUT` を表示しない。
- **影響:**
  - Codex の最終メッセージ、thread_id、帰属確認に使う EVT が、後続の手順から参照できない。
  - `ls -t /tmp/codex-fixer.*` のように推測させると、並列で動いている別の fixer や oracle の出力を読み違える。
- **修正案:**
  - ブロックの末尾で `printf 'OUT=%s\nEVT=%s\nERR=%s\nTHREAD_ID=%s\nFALLBACK=%s\n' …` と `cat "$OUT"` を出力し、`exit $rc` で終了コードを明示する。
  - step 8 では `THREAD_ID='<表示された値>'` と、quoted heredoc で作る `TIGHTER_FOLLOWUP` をブロック内に含める。
  - thread_id は `head -n1` ではなく、`type=="thread.started"` を条件に抽出する。

**M2. SubagentStop フックの出力がモデルに届かない可能性が高い**
- **根拠【事実】:** subagent-scope-audit.py:135-140 は `hookSpecificOutput{hookEventName:"SubagentStop", additionalContext}` を出力している。
- **【要検証】:** 私の知る契約では、`additionalContext` を受け付けるのは UserPromptSubmit / SessionStart / PostToolUse などです。Stop / SubagentStop で使えるのは `decision:"block"` + `reason`（と `systemMessage`）だけのはずです。
- **影響:**
  - 非対応であれば、警告は破棄されるか、デバッグ表示に出るだけです。つまり「決定論的なバックストップ」は実質的に働いていません。
  - README:69, 160 の説明は実態より強く書かれています。
- **修正案:**
  - 親セッションに伝えるには、PostToolUse（matcher `Task|Agent`）で `tool_input.subagent_type` が fixer のときに監査し、`additionalContext` として返す。
  - ユーザーには `systemMessage` で伝える。
  - fixer 自身に対処させたい場合は `decision:"block"` を使い、`stop_hook_active` が真なら再ブロックしない。
  - 誤帰属の可能性がある警告で「restore せよ」と指示する文言（:128-133）は弱める。

**M3. パスの基準が不一致（リポジトリルート基準 / cwd 基準 / 論理パス）**
- **根拠【事実】:**
  - fixer.md:36-46 は、porcelain が出すパスを cwd 基準のまま `[ -f ]` と `cp` に渡している。
  - マニフェストの cwd は `$PWD`（:50-51）。フックはそれを `payload.cwd` と文字列で一致比較する（py:56,76）。
- **前提:** `git status --porcelain` のパスは、`status.relativePaths` を無視して常にリポジトリルート基準です（git-status のドキュメント）。
- **発生条件:** cwd がリポジトリのサブディレクトリにある（モノレポで一般的）。または cwd がシンボリックリンク経由。
- **影響:**
  - dirty ファイルのスナップショットが黙って欠ける。
  - scope 比較で誤警告や見逃しが起きる。
  - フックがマニフェストを見つけられず、何もせずに終わる。
- **修正案:**
  - `git rev-parse --show-toplevel` を基準に、SCOPE_FILES を含む全パスをルート基準に正規化する。`..` や絶対パスは拒否する。
  - 照合は realpath 化したルートで行う。

**M4. 正規の undo 手段が足りず、同時編集を壊しうる**
- **根拠【事実】:**
  - スナップショットの対象は dirty と scope のファイルだけ（fixer.md:34）。
  - step 6 は範囲外の変更を「スナップショットから復元」とする（:94）。しかし開始時に clean だったファイルはスナップショットになく、HEAD への書き戻しは禁止されている（:21）。
  - 帰属の判断材料は EVT の報告と mtime（:93）。
- **影響:**
  - 最も多いケース（開始時に clean だった範囲外ファイルの変更・削除）で、実行できる手順がない。そのため `git show HEAD:… >` のような即興を誘う。
  - シェル経由の変更（フォーマッタ、ロックファイル更新など）は `file_change` に現れない【要検証】。一方、mtime では同じ時間帯のユーザーや他エージェントの編集と区別できない。
  - 復元や削除が不可逆。
- **修正案:**
  - 開始時に `git rev-parse HEAD` と `git ls-files -s -z` も記録する。開始時に clean だったファイルは「記録した blob から `git cat-file blob <sha>` で戻す」ことを正規手順として明記する。
  - restore や delete の前には、必ず現在の内容を退避する（削除は退避先への移動で代える）。
  - 帰属が確定しない場合は触らずに報告する。

**M5. in-scope かつ開始時に dirty だったファイルを、HEAD 基準の diff でレビューしている**
- **根拠【事実】:** fixer.md:97 は `git diff -- <scoped files>` でレビューし、:126 の diff summary も同じ基準。
- **影響:** ユーザーの WIP と Codex の変更が混ざって見えます。Codex が in-scope ファイル内の WIP を消しても、判別できません。
- **修正案:** 開始時に dirty だったファイルは `git diff --no-index -- "$SNAP_DIR/files/<p>" "<p>"` で、開始時点からの差分としてレビュー・報告する。

**M6. `/codex-review` の CLI 例と triage 手順**
- **根拠【事実】:**
  - :15 は「ターゲット指定＋残りの自由文をカスタム指示として後ろに付ける」とし、例は `review --uncommitted … "<instructions>"`（:21-23）。
  - 自由文をダブルクォートで直接書いている。
  - triage は `git diff` / `git diff --cached` / `git show` だけ（:27）。
- **【要検証・確度高め】:** 記憶では、codex-rs の ReviewArgs で `--uncommitted` / `--base` / `--commit` は `[PROMPT]` と排他でした（ReviewTarget の Custom は独立したバリアント）。
- **影響:**
  - 追加指示付きで呼ぶと引数エラーになる。
  - 自由文中の `` ` `` や `$(...)` がシェルで展開される。
  - `base` モードでは、Codex はマージベースからの差分をレビューするのに、triage は作業ツリーの差分しか見ない。未追跡ファイルも見ない。その結果、正しい指摘を棄却しうる。
- **修正案:**
  - 実際の仕様に合わせて分岐する。自由文があるときは、ターゲットを指示文の中に明記したカスタムモードにする（quoted heredoc で組み立て、`--` を付ける）。
  - triage では、`base` なら `git diff "$(git merge-base HEAD "$BASE")"` を使い、未追跡ファイルも確認する。
  - ref は `git rev-parse --verify --end-of-options` で検証する。
  - 「review は設計上 read-only」という主張は未検証なので、`-c 'sandbox_mode="read-only"'` を明示する。
  - review モードで `-o` が書かれるかも確認する。

**M7. バージョン不整合と説明文の古さ**
- **根拠【事実】:**
  - plugin.json:3 は `0.3.0`、marketplace.json:15 は `0.2.0`。
  - marketplace.json:14 の説明に、0.3.0 で削除済みの exploration / research が残っている。
- **影響【要検証】:** どちらのバージョンが優先されるか次第で、更新の検知やキャッシュが食い違います。fable-harness の削除が既存ユーザーに届かない恐れがあります。
- **修正案:** 機能削除なので 0.4.0 が妥当です。可能ならバージョンの記載を 1 箇所にまとめ、説明文も plugin.json に揃えてください。

### 低
- **L1. SCOPE_FILES の例がダブルクォート（fixer.md:31）**
  - `posts.$postId.tsx`（Remix / React Router）や `$postId.tsx`（TanStack Router）が展開されて壊れる。
  - ディレクトリやグロブで scope を指定すると `[ -f ]` で落ちる。
  - 対策: 例をシングルクォートにする。ディレクトリは `git ls-files -co --exclude-standard -z --` で展開し、比較は前方一致にする。
- **L2. 保存場所とマニフェストの紐付け**
  - SNAP_DIR が TMPDIR 配下にある【要検証: workspace-write は既定で `$TMPDIR` と `/tmp` にも書ける】。そのため、監査される側の Codex が復元元を書き換えられる。対策として Codex が書けない 0700 のディレクトリへ移す。
  - 共有 `/tmp/codex-fixer-manifests` の所有者を確認していない。マルチユーザー環境では改ざんでき、`snap_dir` がそのまま警告文に入る。M2 を直した後は、ここがプロンプト注入の経路になる。
  - マニフェストと subagent の紐付けがない（最新の mtime と cwd の一致だけ）。`"fixer" in agent_type` の部分一致で、別の agent（例: bugfixer）が消費しうる。古いマニフェストを拾うこともある。
  - `.json.done` とスナップショットのディレクトリが削除されない。
- **L3. 開始時点の記録でエラーを検査しない（fixer.md:33-52）**
  - `--skip-git-repo-check` を常に付けているので、git リポジトリでない場所や `safe.directory` 不一致でも処理が進み、監査が空になる。
  - フックの `git status` も非 0 終了を検査しない（py:100-107）。失敗すると、全パスを「消失」と誤警告する。
  - 対策: 失敗したら中止する。並列作業との index.lock 競合を避けるため `GIT_OPTIONAL_LOCKS=0` を付ける。
- **L4. Codex 向けの git 禁止が禁止リスト方式（fixer.md:64）**
  - `git apply -R`、`checkout-index -f`、`switch`、`rm`、`mv`、`revert -n` などは禁止されていない。fixer 自身は許可リスト方式（:20）なので揃える。
  - README:158 の「by any means」は、実際にはプロンプト指示に頼っているだけだと明記する（BENCHMARK.md:87 は正確に書けている）。
- **L5. 非 ASCII パスで誤警告（py:30-34）**
  - `core.quotePath` のため日本語のファイル名が一致しない。`.strip()` で末尾の空白も壊れる。H1 の `-z` 化で一緒に直る。
- **L6. フックの command で `${CLAUDE_PLUGIN_ROOT}` をクォートしていない（hooks.json:8,20,32）**
- **L7. 再委譲の往復**
  - codex-implement.md:23 は、Codex が使えないときに lead が手で編集を適用するよう指示している。
  - しかし 20 行以上の編集になると、post-edit-nudge（py:118-124）が fixer への委譲を促すため、また失敗する fixer に戻る余地がある。
  - 対策: この場面では nudge を無視してよいと明記する。

---

## 予定している更新のチェックリスト
- **fable-harness の削除:**
  - 参照は SKILL.md 本体、README.md:57-61（Skills の節）、CHANGELOG.md:7 だけです（grep で確認済み）。
  - CHANGELOG の 0.3.0 は書き換えず、新しいエントリで削除を記載してください。
- **README:**
  - :11 のバッジと :92 の「Tested with」は、実測できた契約と一緒に 0.159.2 / 2.1.285 へ更新してください。
  - :69 と :156-160 は M2 と L4 の結果に合わせて直してください。
  - ベンチマークは v0.2.0 / codex-cli 0.136.0 時点の測定だと明記してください。
- **CHANGELOG:6** の「all Codex calls now use gpt-5.6-sol」は、`/codex-review`（config の既定モデルを使う）と矛盾します。新しいエントリでは正確に書いてください。

## 修正前に実測すべき契約
**Codex 0.159.2**
1. `codex exec review --help` と実際の実行で、次を確認する。
   - ターゲット指定と `[PROMPT]` が排他か
   - `-o` / `--json` / `--skip-git-repo-check` がグローバルか
   - `-s` を受け付けるか
   - review モードで `-o` が書かれるか
2. `codex exec resume --help` で、`-m` などを受け付けるか確認する。resume 時にモデルが引き継がれるかも確認する。
3. 最小の実行（`"Reply OK"`）で次を確認する。
   - 先頭イベントの型と thread_id の位置
   - 存在しないモデルや不正な effort / `max` / `service_tier` を指定したときのエラー文言、出力先（stdout / stderr）、終了コード
4. workspace-write の書き込み可能領域に `$TMPDIR` / `/tmp` が含まれるか、`.git` がどう扱われるか。

**Claude Code 2.1.285**
1. SubagentStop の入力フィールド（`agent_type` / `cwd`）と、出力で有効なフィールド（stdin をファイルに保存する検証用フックと `--debug` で確認）。
2. Bash のタイムアウトの既定値・上限・タイムアウト時の挙動と、subagent がバックグラウンド出力を取得する手段。
3. subagent 起動ツールの名前（Task / Agent）。
4. plugin.json と marketplace のどちらのバージョンが優先されるか。

## カバレッジの限界
- 何も実行していないので、CLI の挙動に関する指摘は知識ベースの【要検証】です。
- benchmarks/run-benchmark.sh は、フィクスチャ専用でユーザーのツリーに触れないことを確認した程度です。
- gpt-5.6-sol が実際に API で使えるかどうかは評価していません。
