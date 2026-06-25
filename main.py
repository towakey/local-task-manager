# main.py
import os
import sys

from parser import expand_instances, fetch_schtasks_csv, parse_csv
from renderer import render_html

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "output.html")


def main():
    print("[1/4] schtasks からタスク情報を取得中...")
    try:
        raw_csv = fetch_schtasks_csv()
    except Exception as e:
        print(f"エラー: schtasks の実行に失敗しました。\n  {e}", file=sys.stderr)
        print("  ヒント: 管理者権限でコマンドプロンプトを開いて実行してください。")
        sys.exit(1)

    print("[2/4] CSVをパースしてTask構造を生成中...")
    tasks = parse_csv(raw_csv)
    if not tasks:
        print("警告: タスクが1件も取得できませんでした。", file=sys.stderr)

    print(f"  → {len(tasks)} タスクを検出")

    print("[3/4] タイムライン用インスタンスに展開中...")
    instances = expand_instances(tasks)
    print(f"  → {len(instances)} 件の実行イベントを生成")

    print("[4/4] HTMLを生成・出力中...")
    html_content = render_html(tasks, instances)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n完了: {OUTPUT_FILE}")
    print("ブラウザで上記ファイルを開いてタイムラインを確認してください。")


if __name__ == "__main__":
    main()
