# renderer.py
import html
from typing import List

from model import Task, TaskInstance

PX_PER_MIN = 1      # 1分 = 1px → 1440px = 24h
TIMELINE_W = 1440   # タイムライン幅（px）
ROW_H = 34          # 行の高さ（px）
BAR_H = 22          # バーの高さ（px）

# タスクごとの色パレット（循環使用）
COLORS = [
    "#4CAF50", "#2196F3", "#FF9800", "#E91E63",
    "#9C27B0", "#00BCD4", "#FF5722", "#3F51B5",
    "#009688", "#FFC107", "#607D8B", "#8BC34A",
    "#F44336", "#03A9F4", "#CDDC39", "#795548",
]


def _assign_colors(tasks: List[Task]) -> dict:
    """タスク名 → カラーコード のマッピングを生成"""
    color_map = {}
    for i, task in enumerate(tasks):
        color_map[task.name] = COLORS[i % len(COLORS)]
    return color_map


def _time_label(minute: int) -> str:
    h = minute // 60
    m = minute % 60
    return f"{h:02d}:{m:02d}"


def render_html(tasks: List[Task], instances: List[TaskInstance]) -> str:
    """TaskInstance リストから HTML文字列を生成する"""

    color_map = _assign_colors(tasks)

    # タスク名ごとに行を割り当て（出現順）
    task_names = list(dict.fromkeys(inst.task_name for inst in instances))
    # タスクが存在しない場合
    if not task_names:
        return _empty_html()

    # バー生成: 同一分・同タスクの重複を行オフセットで積み上げ
    # task_name -> {minute -> count} で重複カウント
    overlap_counter = {}  # (task_name, start_minute) -> count

    bars_by_task = {name: [] for name in task_names}
    for inst in instances:
        key = (inst.task_name, inst.start_minute)
        overlap_counter[key] = overlap_counter.get(key, 0)
        row_offset = overlap_counter[key]
        overlap_counter[key] += 1

        left = inst.start_minute * PX_PER_MIN
        width = max(inst.duration_minute * PX_PER_MIN, 2)  # 最小2px
        top_offset = row_offset * (BAR_H + 2)

        color = color_map.get(inst.task_name, "#4CAF50")
        tooltip = (
            f"タスク: {inst.task_name}&#10;"
            f"開始: {_time_label(inst.start_minute)}&#10;"
            f"実行時間: {inst.duration_minute}分"
        )

        bar_html = (
            f'<div class="bar" '
            f'style="left:{left}px; width:{width}px; background:{color}; top:{top_offset}px;" '
            f'title="{html.escape(tooltip)}">'
            f'</div>'
        )
        bars_by_task[inst.task_name].append(bar_html)

    # 時間軸ラベル（1時間ごと）
    hour_labels = []
    for h in range(25):
        minute = h * 60
        x = minute * PX_PER_MIN
        label = f"{h:02d}:00"
        hour_labels.append(
            f'<div class="hour-label" style="left:{x}px;">{label}</div>'
        )
    hour_grid = "\n".join(hour_labels)

    # タイムライン行
    rows_html = []
    for name in task_names:
        escaped_name = html.escape(name)
        bars = "\n".join(bars_by_task[name])
        row = f"""
        <div class="row">
          <div class="label" title="{escaped_name}">{escaped_name}</div>
          <div class="bar-container">
            {bars}
          </div>
        </div>"""
        rows_html.append(row)

    rows = "\n".join(rows_html)

    # 凡例
    legend_items = []
    for name in task_names:
        color = color_map.get(name, "#4CAF50")
        legend_items.append(
            f'<div class="legend-item">'
            f'<span class="legend-color" style="background:{color};"></span>'
            f'<span>{html.escape(name)}</span>'
            f'</div>'
        )
    legend = "\n".join(legend_items)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>タスクスケジューラ タイムライン</title>
<style>
* {{
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}}
body {{
  font-family: "Meiryo", "Yu Gothic", sans-serif;
  background: #f5f5f5;
  color: #333;
  padding: 16px;
}}
h1 {{
  font-size: 18px;
  margin-bottom: 12px;
  color: #1a237e;
}}
.meta {{
  font-size: 12px;
  color: #777;
  margin-bottom: 16px;
}}
/* ---- フィルタ ---- */
#filter-box {{
  margin-bottom: 12px;
}}
#filter-input {{
  padding: 6px 10px;
  border: 1px solid #ccc;
  border-radius: 4px;
  width: 320px;
  font-size: 13px;
}}
/* ---- タイムライン外枠 ---- */
.timeline-wrapper {{
  overflow-x: auto;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: #fff;
  padding-bottom: 8px;
}}
.timeline-inner {{
  min-width: {TIMELINE_W + 180}px;
}}
/* ---- 時間軸 ---- */
.hour-axis {{
  position: relative;
  height: 24px;
  margin-left: 180px;
  border-bottom: 2px solid #aaa;
  margin-bottom: 4px;
}}
.hour-label {{
  position: absolute;
  font-size: 10px;
  color: #555;
  transform: translateX(-50%);
  white-space: nowrap;
}}
/* ---- 行 ---- */
.row {{
  display: flex;
  align-items: flex-start;
  border-bottom: 1px solid #f0f0f0;
  min-height: {ROW_H}px;
  padding: 4px 0;
}}
.row:hover {{
  background: #fafafa;
}}
.label {{
  width: 180px;
  min-width: 180px;
  font-size: 11px;
  padding: 2px 8px;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: {BAR_H}px;
}}
.bar-container {{
  position: relative;
  width: {TIMELINE_W}px;
  min-width: {TIMELINE_W}px;
  height: {ROW_H}px;
}}
/* ---- バー ---- */
.bar {{
  position: absolute;
  height: {BAR_H}px;
  border-radius: 3px;
  opacity: 0.85;
  cursor: pointer;
  transition: opacity 0.15s;
}}
.bar:hover {{
  opacity: 1;
  outline: 2px solid #333;
  z-index: 10;
}}
/* ---- 縦グリッド線 ---- */
.grid-line {{
  position: absolute;
  top: 0;
  width: 1px;
  height: 100%;
  background: #e8e8e8;
  pointer-events: none;
}}
/* ---- 凡例 ---- */
.legend {{
  margin-top: 20px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}}
.legend-item {{
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 4px;
  padding: 3px 7px;
}}
.legend-color {{
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 2px;
  flex-shrink: 0;
}}
</style>
</head>
<body>
<h1>タスクスケジューラ タイムライン</h1>
<div class="meta">対象タスク数: {len(task_names)} 件 ／ 実行イベント数: {len(instances)} 件</div>

<div id="filter-box">
  <input id="filter-input" type="text" placeholder="タスク名でフィルタ..." oninput="filterRows(this.value)">
</div>

<div class="timeline-wrapper">
  <div class="timeline-inner">
    <!-- 時間軸 -->
    <div class="hour-axis" id="hour-axis">
      {hour_grid}
    </div>
    <!-- 行 -->
    <div id="timeline-rows">
      {rows}
    </div>
  </div>
</div>

<!-- 凡例 -->
<div class="legend">
  {legend}
</div>

<script>
(function() {{
  // 縦グリッド線を動的に描画
  var axis = document.getElementById('hour-axis');
  for (var h = 0; h <= 24; h++) {{
    var line = document.createElement('div');
    line.className = 'grid-line';
    line.style.left = (h * 60) + 'px';
    axis.appendChild(line);
  }}
}})();

function filterRows(keyword) {{
  var rows = document.querySelectorAll('#timeline-rows .row');
  var kw = keyword.trim().toLowerCase();
  rows.forEach(function(row) {{
    var label = row.querySelector('.label');
    if (!label) return;
    var name = label.textContent.toLowerCase();
    row.style.display = (!kw || name.indexOf(kw) !== -1) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""


def _empty_html() -> str:
    return """<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><title>タスクスケジューラ タイムライン</title></head>
<body>
<h1>タスクスケジューラ タイムライン</h1>
<p>表示できるタスクが見つかりませんでした。管理者権限で実行してください。</p>
</body>
</html>
"""
