"""
Модуль диспетчера очереди загрузок (core.queue)

Обеспечивает:
- Добавление задач в очередь с сохранением всех настроек
- Последовательную обработку задач в фоновом потоке
- Оповещение интерфейса об изменении прогресса каждого элемента
- Возможность приостановки, возобновления и очистки очереди
"""

import threading
import time
import uuid
from typing import Dict, Any, List, Optional, Callable


class DownloadTask:
    """
    Класс отдельной задачи в очереди.
    """

    def __init__(
        self,
        media_type: str,
        title: str,
        url: str,
        options: Dict[str, Any],
        thumbnail_url: Optional[str] = None,
        duration_str: Optional[str] = None,
    ):
        self.id = str(uuid.uuid4())[:8]
        self.task_id = self.id
        self.media_type = media_type  # "video", "audio", "playlist"
        self.title = title
        self.url = url
        self.thumbnail_url = thumbnail_url
        self.duration_str = duration_str or "--:--"
        self.options = options

        self.status = "pending"  # "pending", "downloading", "completed", "error", "paused"
        self.progress_fraction = 0.0
        self.progress_percent = 0.0
        self.speed_str = "-- МБ/с"
        self.eta_str = "--:--"
        self.error_message: Optional[str] = None
        self.output_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "media_type": self.media_type,
            "title": self.title,
            "url": self.url,
            "thumbnail_url": self.thumbnail_url,
            "duration_str": self.duration_str,
            "options": self.options,
            "status": self.status,
            "progress_fraction": self.progress_fraction,
            "progress_percent": self.progress_percent,
            "speed_str": self.speed_str,
            "eta_str": self.eta_str,
            "error_message": self.error_message,
            "output_path": self.output_path,
        }


class DownloadQueueManager:
    """
    Потокобезопасный менеджер пакетной очереди загрузок.
    """

    def __init__(self):
        self.tasks: List[DownloadTask] = []
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._stop_event = threading.Event()

    def add_task(
        self,
        media_type: str,
        title: str,
        url: str,
        options: Dict[str, Any],
        thumbnail_url: Optional[str] = None,
        duration_str: Optional[str] = None,
    ) -> DownloadTask:
        task = DownloadTask(
            media_type=media_type,
            title=title,
            url=url,
            options=options,
            thumbnail_url=thumbnail_url,
            duration_str=duration_str,
        )
        with self._lock:
            self.tasks.append(task)
        return task

    def remove_task(self, task_id: str) -> None:
        with self._lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]

    def clear_completed(self) -> None:
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status not in ("completed", "error")]

    def clear_all(self) -> None:
        with self._lock:
            self.tasks.clear()

    def get_tasks(self) -> List[DownloadTask]:
        with self._lock:
            return list(self.tasks)

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        with self._lock:
            for t in self.tasks:
                if t.id == task_id:
                    return t
        return None

    def is_running(self) -> bool:
        return self._is_running

    def start(
        self,
        worker_func: Callable[[DownloadTask, Callable[[Dict[str, Any]], None], Callable[[str], None]], Dict[str, Any]],
        on_task_update: Callable[[DownloadTask], None],
        on_queue_finished: Callable[[], None],
    ) -> None:
        """
        Запускает фоновую обработку очереди.
        """
        if self._is_running:
            return

        self._is_running = True
        self._stop_event.clear()

        def _loop():
            while self._is_running and not self._stop_event.is_set():
                next_task = None
                with self._lock:
                    for t in self.tasks:
                        if t.status == "pending":
                            next_task = t
                            break

                if not next_task:
                    break

                next_task.status = "downloading"
                next_task.progress_fraction = 0.0
                next_task.progress_percent = 0.0
                on_task_update(next_task)

                def on_progress(p_data: Dict[str, Any]):
                    next_task.progress_fraction = p_data.get("fraction", 0.0)
                    next_task.progress_percent = p_data.get("percent", 0.0)
                    next_task.speed_str = p_data.get("speed_str", "-- МБ/с")
                    next_task.eta_str = p_data.get("eta_str", "--:--")
                    on_task_update(next_task)

                def on_status(status_msg: str):
                    on_task_update(next_task)

                try:
                    res = worker_func(next_task, on_progress, on_status)
                    if self._stop_event.is_set():
                        next_task.status = "paused"
                    else:
                        next_task.status = "completed"
                        next_task.progress_fraction = 1.0
                        next_task.progress_percent = 100.0
                        next_task.output_path = res.get("file_path") if res else None
                except Exception as exc:
                    if self._stop_event.is_set():
                        next_task.status = "paused"
                    else:
                        next_task.status = "error"
                        next_task.error_message = str(exc)

                try:
                    on_task_update(next_task)
                except Exception:
                    pass
                time.sleep(0.5)

            self._is_running = False
            try:
                on_queue_finished()
            except Exception:
                pass

        self._worker_thread = threading.Thread(target=_loop, daemon=True)
        self._worker_thread.start()

    def pause(self) -> None:
        self._stop_event.set()
        self._is_running = False

    def stop(self) -> None:
        self.pause()
