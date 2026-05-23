"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, tuple] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._completed = set()
        self._max_retries = 3

    def decode_and_validate_payload(self, payload: Any) -> Optional[Dict]:
        """Decode and validate job payload safely, handling legacy formats."""
        if payload is None:
            logger.warning("Rejecting empty/None job payload")
            return None

        if isinstance(payload, str):
            try:
                import json
                payload = json.loads(payload)
            except Exception as e:
                logger.warning(f"Rejecting malformed JSON string payload: {e}")
                return None

        if not isinstance(payload, dict):
            logger.warning(f"Rejecting invalid payload type: {type(payload)}")
            return None

        if "id" not in payload:
            payload["id"] = str(uuid4())

        if not payload.get("type") and not payload.get("target_agent"):
            logger.warning("Rejecting payload lacking vital fields (type or target_agent)")
            return None

        return payload

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        validated_task = self.decode_and_validate_payload(task)
        if not validated_task:
            raise ValueError("Malformed job payload")

        task_id = validated_task["id"]

        if task_id in self._completed:
            logger.warning(f"Rejecting enqueue for completed task {task_id}")
            return task_id

        if task_id in self._in_flight:
            logger.warning(f"Rejecting enqueue for in-flight task {task_id}")
            return task_id

        if task_id in self._scheduled:
            val = self._scheduled[task_id]
            scheduled_time = val[0]
            if time.monotonic() < scheduled_time:
                logger.warning(f"Rejecting enqueue for delayed task {task_id} before schedule time")
                return task_id

        validated_task["enqueued_at"] = time.monotonic()
        if "retries" not in validated_task:
            validated_task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(validated_task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        validated_task = self.decode_and_validate_payload(task)
        if not validated_task:
            raise ValueError("Malformed job payload")

        task_id = validated_task["id"]
        self._scheduled[task_id] = (time.monotonic() + delay, validated_task, queue, priority)
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.monotonic()
        expired = [tid for tid, val in list(self._scheduled.items()) if val[0] <= now]
        for tid in expired:
            val = self._scheduled.pop(tid, None)
            if val:
                if len(val) == 2:
                    t_time, task = val
                    t_queue = queue
                    t_priority = 0
                else:
                    t_time, task, t_queue, t_priority = val
                
                try:
                    self.enqueue(task, t_queue, t_priority)
                except ValueError as e:
                    logger.warning(f"Failed to enqueue expired task {tid}: {e}")

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                validated = self.decode_and_validate_payload(task)
                if not validated:
                    logger.warning("Discarding malformed task popped from queue")
                    return await self.dequeue(queue, timeout)
                
                task_id = validated["id"]
                if task_id in self._completed:
                    logger.warning(f"Discarding completed task {task_id} popped from queue")
                    return await self.dequeue(queue, timeout)
                
                self._in_flight[task_id] = validated
                return validated
        return None

    def complete(self, task_id: str) -> bool:
        if task_id in self._completed:
            return True
        task = self._in_flight.pop(task_id, None)
        if task:
            self._completed.add(task_id)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        if task_id in self._completed:
            return False
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
            else:
                self._completed.add(task_id)
        return False

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
