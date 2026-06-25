# model.py
import datetime
from typing import List, Optional


class Trigger:
    """タスクのトリガー情報"""

    def __init__(
        self,
        type: str,
        start_time: datetime.time,
        interval_min: Optional[int] = None,
        duration_min: Optional[int] = None,
    ):
        self.type = type                  # ONCE / DAILY / WEEKLY / MONTHLY / REPEAT
        self.start_time = start_time      # 開始時刻
        self.interval_min = interval_min  # 繰り返し間隔（分）
        self.duration_min = duration_min  # 繰り返し継続時間（分）

    def __repr__(self):
        return (
            f"Trigger(type={self.type!r}, start_time={self.start_time}, "
            f"interval_min={self.interval_min}, duration_min={self.duration_min})"
        )


class Task:
    """タスクスケジューラの1タスク"""

    def __init__(
        self,
        name: str,
        triggers: Optional[List[Trigger]] = None,
        avg_duration_sec: int = 60,
    ):
        self.name = name
        self.triggers: List[Trigger] = triggers if triggers is not None else []
        self.avg_duration_sec = avg_duration_sec  # 推定実行時間（秒）

    def __repr__(self):
        return f"Task(name={self.name!r}, triggers={self.triggers})"


class TaskInstance:
    """タイムライン上に展開された1実行イベント"""

    def __init__(
        self,
        task_name: str,
        start_minute: int,
        duration_minute: int,
    ):
        self.task_name = task_name
        self.start_minute = start_minute    # 0〜1440
        self.duration_minute = duration_minute

    def __repr__(self):
        return (
            f"TaskInstance(task_name={self.task_name!r}, "
            f"start_minute={self.start_minute}, duration_minute={self.duration_minute})"
        )
