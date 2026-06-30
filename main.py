# main.py
import os
import sys

from task_parser import (
    apply_eventlog_durations,
    expand_instances,
    fetch_eventlog_durations,
    fetch_schtasks_csv,
    parse_csv,
)
from renderer import render_html

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "output.html")


def main():
    print("[1/5] schtasks からタスク情報を取得中...")
    try:
        raw_csv = fetch_schtasks_csv()
    except Exception as e:
        print(f"エラー: schtasks の実行に失敗しました。\n  {e}", file=sys.stderr)
        print("  ヒント: 管理者権限でコマンドプロンプトを開いて実行してください。")
        sys.exit(1)

    # CSVヘッダー表示（デバッグ用）
    import csv, io
    first_line = raw_csv.split("\n", 1)[0]
    print(f"  CSVヘッダー: {first_line}")

    print("[2/5] CSVをパースしてTask構造を生成中...")
    tasks = parse_csv(raw_csv)
    if not tasks:
        print("警告: タスクが1件も取得できませんでした。", file=sys.stderr)

    print(f"  → {len(tasks)} タスクを検出")
    tasks_with_cmd = [t for t in tasks if t.command]
    print(f"  → うち {len(tasks_with_cmd)} タスクに実行プログラム情報あり")
    if tasks and not tasks_with_cmd:
        print("  ※ 実行プログラムが取得できていません。CSVヘッダーを確認してください。")

    print("[3/5] イベントログから実行履歴を取得中...")
    try:
        durations = fetch_eventlog_durations()
        if durations:
            applied = apply_eventlog_durations(tasks, durations)
            print(f"  → {len(durations)} 件の実行履歴を取得、{applied} タスクに適用")
        else:
            print("  → イベントログから実行履歴を取得できませんでした（fallback使用）")
    except Exception as e:
        print(f"  → イベントログ取得スキップ: {e}")

    print("[4/5] タイムライン用インスタンスに展開中...")
    instances = expand_instances(tasks)
    print(f"  → {len(instances)} 件の実行イベントを生成")

    print("[5/5] HTMLを生成・出力中...")
    html_content = render_html(tasks, instances)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n完了: {OUTPUT_FILE}")
    print("ブラウザで上記ファイルを開いてタイムラインを確認してください。")


if __name__ == "__main__":
    main()
