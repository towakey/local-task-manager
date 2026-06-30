# task_parser.py
import csv
import datetime
import io
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

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
        "Task To Run":     ["実行するタスク", "操作", "タスクの実行", "Task To Run"],
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

        # 実行プログラム（フルパス）
        command = get_field(row, "Task To Run").strip()

        # 実行時間推定（方法A: Last Run Time と Next Run Time 差分）
        avg_duration_sec = _estimate_duration(
            get_field(row, "Last Run Time"),
            get_field(row, "Next Run Time"),
        )

        if task_name not in tasks_map:
            tasks_map[task_name] = Task(
                name=task_name,
                avg_duration_sec=avg_duration_sec,
                command=command,
            )
        else:
            # 既存タスクの duration を更新（より良い推定値があれば上書き）
            if avg_duration_sec != DEFAULT_DURATION_SEC:
                tasks_map[task_name].avg_duration_sec = avg_duration_sec
            # command が空の場合のみ更新
            if command and not tasks_map[task_name].command:
                tasks_map[task_name].command = command

        tasks_map[task_name].triggers.append(trigger)

    return list(tasks_map.values())


def apply_eventlog_durations(tasks: List[Task], durations: Dict[str, int]) -> int:
    """
    イベントログから取得した実行時間をタスクに適用する。
    Returns: 適用したタスク数
    """
    applied = 0
    for task in tasks:
        # イベントログのタスク名は "\folder\name" 形式
        if task.name in durations:
            task.avg_duration_sec = durations[task.name]
            applied += 1
        else:
            # 末尾のタスク名部分でマッチを試みる
            for ev_name, dur in durations.items():
                if ev_name.endswith(task.name) or task.name.endswith(ev_name):
                    task.avg_duration_sec = dur
                    applied += 1
                    break
    return applied


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
# イベントログから実行履歴を取得
# ---------------------------------------------------------------------------

def fetch_eventlog_durations() -> Dict[str, int]:
    """
    Windowsイベントログ（TaskScheduler/Operational）から
    タスクごとの前回実行時間（秒）を取得する。

    EventID 100 = タスク開始
    EventID 102 = タスク完了

    Returns:
        {task_name: duration_sec} の辞書。取得できない場合は空辞書。
    """
    try:
        xml_str = subprocess.check_output(
            [
                "wevtutil", "qe",
                "Microsoft-Windows-TaskScheduler/Operational",
                "/q:*[System[(EventID=100 or EventID=102)]]",
                "/c:2000",
                "/rd:true",
                "/f:xml",
            ],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return {}

    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            decoded = xml_str.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return {}

    # wevtutilの出力は複数の<Event>要素が並ぶがルート要素がない
    decoded = "<Events>" + decoded + "</Events>"
    # XML名前空間を除去（パースを簡素化）
    decoded = re.sub(r'\sxmlns(:[^=]*)?="[^"]*"', '', decoded)

    try:
        root = ET.fromstring(decoded)
    except ET.ParseError:
        return {}

    # イベントを収集: (task_name, event_id, timestamp)
    events = []  # type: List[Tuple[str, int, datetime.datetime]]
    for event_el in root.findall(".//Event"):
        system_el = event_el.find("System")
        if system_el is None:
            continue
        event_id_el = system_el.find("EventID")
        time_el = system_el.find("TimeCreated")
        if event_id_el is None or time_el is None:
            continue

        try:
            event_id = int(event_id_el.text)
        except (ValueError, TypeError):
            continue

        time_str = time_el.get("SystemTime", "")
        if not time_str:
            continue

        # ISO 8601 形式: 2024-01-15T08:30:00.1234567Z
        time_str = time_str.replace("Z", "+00:00")
        # ナノ秒精度をマイクロ秒に丸める（Python 3.7互換）
        time_str = re.sub(r'(\d{2}:\d{2}:\d{2})\.\d+', r'\1', time_str)
        try:
            ts = datetime.datetime.fromisoformat(time_str)
        except (ValueError, AttributeError):
            continue

        # EventDataからタスク名を取得
        event_data = event_el.find("EventData")
        task_name = ""
        if event_data is not None:
            for data_el in event_data.findall("Data"):
                if data_el.get("Name") == "TaskName":
                    task_name = (data_el.text or "").strip()
                    break
        if not task_name:
            continue

        events.append((task_name, event_id, ts))

    # タスク名ごとに最新の開始(100)・完了(102)ペアを見つけてdurationを計算
    # イベントは新しい順に取得済み（/rd:true）
    durations = {}  # type: Dict[str, int]
    # タスク名ごとに最新の完了イベントを見つけ、その直前の開始イベントとペアリング
    task_events = {}  # type: Dict[str, List[Tuple[int, datetime.datetime]]]
    for task_name, event_id, ts in events:
        if task_name not in task_events:
            task_events[task_name] = []
        task_events[task_name].append((event_id, ts))

    for task_name, evts in task_events.items():
        # 時系列順にソート（古い順）
        evts.sort(key=lambda x: x[1])
        last_start = None  # type: Optional[datetime.datetime]
        last_duration = None  # type: Optional[int]
        for event_id, ts in evts:
            if event_id == 100:
                last_start = ts
            elif event_id == 102 and last_start is not None:
                diff = (ts - last_start).total_seconds()
                if 0 < diff <= 86400:  # 0秒超〜24時間以内
                    last_duration = int(diff)
                last_start = None
        if last_duration is not None:
            durations[task_name] = last_duration

    return durations


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
