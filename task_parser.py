# parser.py
import csv
import datetime
import io
import subprocess
from typing import List, Optional

from model import Task, TaskInstance, Trigger

DEFAULT_DURATION_SEC = 60  # fallback 実行時間（秒）
PX_PER_MIN = 1             # 1分 = 1px（1440px = 24h）


# ---------------------------------------------------------------------------
# STEP 1: schtasks からCSV取得
# ---------------------------------------------------------------------------

def fetch_schtasks_csv() -> str:
    """schtasks /query /v /fo csv を実行してCSV文字列を返す"""
    result = subprocess.check_output(
        ["schtasks", "/query", "/v", "/fo", "csv"],
        stderr=subprocess.DEVNULL,
    )
    # Windows はshift_jis / cp932 で出力されることが多い
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return result.decode(enc)
        except UnicodeDecodeError:
            continue
    return result.decode("cp932", errors="replace")


# ---------------------------------------------------------------------------
# STEP 2: CSVパース → Task リスト生成
# ---------------------------------------------------------------------------

def _parse_time(value: str) -> Optional[datetime.time]:
    """HH:MM:SS または HH:MM 形式の文字列を datetime.time に変換"""
    value = value.strip()
    for fmt in ("%H:%M:%S", "%I:%M:%S %p", "%H:%M", "%I:%M %p"):
        try:
            return datetime.datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def _parse_interval_minutes(value: str) -> Optional[int]:
    """
    'Repeat: Every' フィールドの値をパース。
    例: '0 Hour(s), 10 Minute(s)' → 10
        '1 Hour(s), 0 Minute(s)' → 60
        '無効' / 'N/A' / '' → None
    """
    value = value.strip()
    if not value or value.upper() in ("N/A", "無効", "DISABLED"):
        return None
    minutes = 0
    import re
    m = re.search(r"(\d+)\s*Hour", value, re.IGNORECASE)
    if m:
        minutes += int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*Minute", value, re.IGNORECASE)
    if m:
        minutes += int(m.group(1))
    return minutes if minutes > 0 else None


def _parse_duration_minutes(value: str) -> Optional[int]:
    """
    'Repeat: Until: Duration' フィールドの値をパース。
    例: '1 Hour(s), 0 Minute(s)' → 60
    """
    return _parse_interval_minutes(value)


def _normalize_type(schedule_type: str) -> str:
    """スケジュール種別を正規化"""
    s = schedule_type.strip().upper()
    if "DAILY" in s or "毎日" in s:
        return "DAILY"
    if "WEEKLY" in s or "毎週" in s:
        return "WEEKLY"
    if "MONTHLY" in s or "毎月" in s:
        return "MONTHLY"
    if "ONE" in s or "ONCE" in s or "1 TIME" in s or "一度" in s:
        return "ONCE"
    if "REPEAT" in s or "繰り返し" in s:
        return "REPEAT"
    return "UNKNOWN"


def parse_csv(raw_csv: str) -> List[Task]:
    """
    schtasks CSV を Task リストに変換する。
    同一タスク名の複数行（トリガーが複数）はひとつの Task にまとめる。
    """
    reader = csv.DictReader(io.StringIO(raw_csv))

    # フィールド名の揺れを吸収するマッピング
    FIELD_ALIASES = {
        "TaskName":        ["タスク名", "TaskName", "HostName"],  # HostNameは除外用
        "Next Run Time":   ["次回の実行時刻", "Next Run Time"],
        "Schedule Type":   ["スケジュールの種類", "Schedule Type"],
        "Start Time":      ["開始時刻", "Start Time"],
        "Start Date":      ["開始日", "Start Date"],
        "Repeat: Every":   ["繰り返し: 間隔", "Repeat: Every"],
        "Repeat: Until: Duration": ["繰り返し: 期間", "Repeat: Until: Duration"],
        "Last Run Time":   ["最終実行時刻", "Last Run Time"],
        "Last Result":     ["最終結果", "Last Result"],
        "Status":          ["状態", "Status"],
    }

    def get_field(row: dict, key: str) -> str:
        for alias in FIELD_ALIASES.get(key, [key]):
            if alias in row:
                return row[alias] or ""
        return ""

    tasks_map = {}  # task_name -> Task

    for row in reader:
        task_name = get_field(row, "TaskName").strip()
        if not task_name or task_name.startswith("HostName"):
            continue

        # 無効タスクはスキップ
        status = get_field(row, "Status").strip().upper()
        if status in ("無効", "DISABLED"):
            continue

        start_time_str = get_field(row, "Start Time")
        start_time = _parse_time(start_time_str)
        if start_time is None:
            continue  # 開始時刻が取れないトリガーは無視

        schedule_type = _normalize_type(get_field(row, "Schedule Type"))
        interval_min = _parse_interval_minutes(get_field(row, "Repeat: Every"))
        duration_min = _parse_duration_minutes(get_field(row, "Repeat: Until: Duration"))

        # 繰り返し間隔がある場合は REPEAT として扱う
        if interval_min is not None:
            schedule_type = "REPEAT"

        trigger = Trigger(
            type=schedule_type,
            start_time=start_time,
            interval_min=interval_min,
            duration_min=duration_min,
        )

        # 実行時間推定（方法A: Last Run Time と Next Run Time 差分）
        avg_duration_sec = _estimate_duration(
            get_field(row, "Last Run Time"),
            get_field(row, "Next Run Time"),
        )

        if task_name not in tasks_map:
            tasks_map[task_name] = Task(
                name=task_name,
                avg_duration_sec=avg_duration_sec,
            )
        else:
            # 既存タスクの duration を更新（より良い推定値があれば上書き）
            if avg_duration_sec != DEFAULT_DURATION_SEC:
                tasks_map[task_name].avg_duration_sec = avg_duration_sec

        tasks_map[task_name].triggers.append(trigger)

    return list(tasks_map.values())


def _estimate_duration(last_run_str: str, next_run_str: str) -> int:
    """
    方法A: Last Run Time と Next Run Time の差から推定。
    差が1日以上 or 取得不可 の場合は DEFAULT_DURATION_SEC を返す。
    """
    for fmt in (
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            last = datetime.datetime.strptime(last_run_str.strip(), fmt)
            nxt = datetime.datetime.strptime(next_run_str.strip(), fmt)
            diff = abs((nxt - last).total_seconds())
            # 差分が 5秒〜1時間 なら採用（それ以外は精度が低すぎる）
            if 5 <= diff <= 3600:
                return int(diff)
            break
        except (ValueError, AttributeError):
            continue
    return DEFAULT_DURATION_SEC


# ---------------------------------------------------------------------------
# STEP 3: Trigger を TaskInstance に展開
# ---------------------------------------------------------------------------

def expand_instances(tasks: List[Task]) -> List[TaskInstance]:
    """Task リストを1日分の TaskInstance リストに展開する"""
    instances = []
    for task in tasks:
        duration_min = max(1, task.avg_duration_sec // 60)
        for trigger in task.triggers:
            _expand_trigger(task.name, trigger, duration_min, instances)
    return instances


def _expand_trigger(
    task_name: str,
    trigger: Trigger,
    duration_min: int,
    instances: List[TaskInstance],
):
    """1トリガーを展開して instances に追加する"""
    start_min = trigger.start_time.hour * 60 + trigger.start_time.minute

    if trigger.type == "REPEAT" and trigger.interval_min:
        interval = trigger.interval_min
        # 継続時間が指定されている場合はその範囲内、なければ00:00まで
        if trigger.duration_min:
            end_min = min(start_min + trigger.duration_min, 1440)
        else:
            end_min = 1440

        t = start_min
        while t < end_min:
            if 0 <= t < 1440:
                instances.append(TaskInstance(
                    task_name=task_name,
                    start_minute=t,
                    duration_minute=duration_min,
                ))
            t += interval
    else:
        # ONCE / DAILY / WEEKLY / MONTHLY → そのまま1件
        if 0 <= start_min < 1440:
            instances.append(TaskInstance(
                task_name=task_name,
                start_minute=start_min,
                duration_minute=duration_min,
            ))
