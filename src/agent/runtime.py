"""Agent Runtime — Manages agent process lifecycle."""

import os
import signal
import subprocess
import logging
import time
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RuntimeState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    CRASHED = "crashed"


class AgentRuntime:
    def __init__(self):
        self._processes: Dict[str, subprocess.Popen] = {}
        self._states: Dict[str, RuntimeState] = {}
        self._start_times: Dict[str, float] = {}
        self._heartbeats: Dict[str, float] = {}
        self._terminal_outcomes: Dict[str, str] = {}
        self._locks: Dict[str, bool] = {}

    def start(self, agent_id: str, command: list, env: Optional[Dict] = None) -> bool:
        if agent_id in self._processes and self._processes[agent_id].poll() is None:
            logger.warning(f"Agent {agent_id} is already running")
            return False

        self._terminal_outcomes.pop(agent_id, None)
        self._heartbeats.pop(agent_id, None)

        self._states[agent_id] = RuntimeState.STARTING
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        process_env["AO_AGENT_ID"] = agent_id

        try:
            proc = subprocess.Popen(
                command,
                env=process_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._processes[agent_id] = proc
            self._start_times[agent_id] = time.monotonic()
            self._states[agent_id] = RuntimeState.RUNNING
            self._locks[agent_id] = True
            self._heartbeats[agent_id] = time.monotonic()
            logger.info(f"Agent {agent_id} started (PID: {proc.pid})")
            return True
        except Exception as e:
            self._states[agent_id] = RuntimeState.CRASHED
            self._terminal_outcomes[agent_id] = "crashed"
            logger.error(f"Failed to start agent {agent_id}: {e}")
            return False

    def stop(self, agent_id: str, timeout: int = 10) -> bool:
        proc = self._processes.get(agent_id)
        if not proc or proc.poll() is not None:
            self._locks.pop(agent_id, None)
            self._heartbeats.pop(agent_id, None)
            return False

        self._states[agent_id] = RuntimeState.STOPPING
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        self._states[agent_id] = RuntimeState.STOPPED
        self._terminal_outcomes[agent_id] = "stopped"
        self._start_times.pop(agent_id, None)
        self._heartbeats.pop(agent_id, None)
        self._locks.pop(agent_id, None)
        logger.info(f"Agent {agent_id} stopped")
        return True

    def record_terminal_outcome(self, agent_id: str, outcome: str) -> None:
        """Record one durable terminal outcome and release locks."""
        if agent_id in self._terminal_outcomes:
            return
        self._terminal_outcomes[agent_id] = outcome
        self._states[agent_id] = RuntimeState.STOPPED
        self._locks.pop(agent_id, None)
        self._start_times.pop(agent_id, None)
        self._heartbeats.pop(agent_id, None)

    def heartbeat(self, agent_id: str) -> bool:
        """Record worker heartbeat, preventing revival of completed runs."""
        if agent_id in self._terminal_outcomes:
            logger.warning(f"Heartbeat rejected: agent {agent_id} has completed with outcome '{self._terminal_outcomes[agent_id]}'")
            return False
            
        current_state = self.get_state(agent_id)
        if current_state in (RuntimeState.STOPPED, RuntimeState.STOPPING, RuntimeState.CRASHED):
            logger.warning(f"Heartbeat rejected: agent {agent_id} is in completed state {current_state}")
            return False
            
        self._heartbeats[agent_id] = time.monotonic()
        return True

    def check_heartbeats(self, timeout_seconds: int) -> list[str]:
        """Check for missing heartbeats and terminate dead workers."""
        timed_out = []
        now = time.monotonic()
        for agent_id, last_hb in list(self._heartbeats.items()):
            if self.get_state(agent_id) == RuntimeState.RUNNING:
                if (now - last_hb) > timeout_seconds:
                    logger.warning(f"Agent {agent_id} heartbeat timeout. Terminating.")
                    self.stop(agent_id)
                    self._states[agent_id] = RuntimeState.CRASHED
                    self._terminal_outcomes[agent_id] = "heartbeat_timeout"
                    timed_out.append(agent_id)
        return timed_out

    def get_state(self, agent_id: str) -> RuntimeState:
        if agent_id in self._terminal_outcomes:
            return RuntimeState.STOPPED
            
        proc = self._processes.get(agent_id)
        if proc and proc.poll() is not None:
            if self._states.get(agent_id) not in (RuntimeState.STOPPED, RuntimeState.STOPPING):
                self._states[agent_id] = RuntimeState.CRASHED
                self._terminal_outcomes[agent_id] = "crashed"
                self._locks.pop(agent_id, None)
                self._heartbeats.pop(agent_id, None)
        return self._states.get(agent_id, RuntimeState.STOPPED)

    def is_running(self, agent_id: str) -> bool:
        proc = self._processes.get(agent_id)
        return proc is not None and proc.poll() is None

    def check_timeouts(self, timeout_seconds: int) -> list[str]:
        timed_out_agents = []
        now = time.monotonic()
        for agent_id, proc in list(self._processes.items()):
            if proc.poll() is None:
                start_time = self._start_times.get(agent_id)
                if start_time is not None and (now - start_time) > timeout_seconds:
                    logger.warning(f"Agent {agent_id} timed out. Terminating.")
                    self._states[agent_id] = RuntimeState.STOPPING
                    proc.send_signal(signal.SIGTERM)
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    self._states[agent_id] = RuntimeState.CRASHED
                    self._start_times.pop(agent_id, None)
                    timed_out_agents.append(agent_id)
            else:
                self._start_times.pop(agent_id, None)
        return timed_out_agents

# 2019-01-11T10:56:26 update

# 2019-01-22T16:22:30 update

# 2019-03-06T18:13:59 update

# 2019-03-15T11:30:26 update

# 2019-03-18T11:22:04 update

# 2019-03-29T09:30:22 update

# 2019-05-06T17:17:42 update

# 2019-07-08T10:46:12 update

# 2019-10-30T15:01:34 update

# 2019-11-21T11:46:57 update

# 2019-12-09T13:23:07 update

# 2020-02-18T14:01:01 update

# 2020-02-19T11:51:07 update

# 2020-02-27T18:21:42 update

# 2020-03-11T12:29:19 update

# 2020-04-13T09:40:09 update

# 2020-06-16T14:21:27 update

# 2020-08-12T12:56:50 update

# 2020-08-13T09:41:21 update

# 2020-09-10T08:08:18 update

# 2020-10-02T12:22:16 update

# 2020-10-14T13:05:00 update

# 2020-10-19T14:32:13 update

# 2021-02-11T08:23:22 update

# 2021-02-19T19:20:29 update

# 2021-03-24T19:22:02 update

# 2021-09-03T16:39:23 update

# 2021-10-11T10:52:21 update

# 2021-12-13T09:33:23 update

# 2022-01-04T11:11:07 update

# 2022-07-31T15:24:35 update

# 2022-08-05T19:33:09 update

# 2022-10-07T20:08:25 update

# 2022-10-20T09:57:32 update

# 2023-01-06T17:26:45 update

# 2023-01-12T18:21:36 update

# 2023-03-30T19:52:43 update

# 2023-06-06T16:53:33 update

# 2023-09-21T18:21:37 update

# 2024-01-02T10:34:11 update

# 2024-01-04T10:43:54 update

# 2024-03-28T11:14:49 update

# 2024-04-22T10:30:24 update

# 2024-05-16T14:19:27 update

# 2024-06-04T10:50:47 update

# 2024-08-08T20:51:15 update

# 2024-10-14T18:24:05 update

# 2024-10-28T09:06:13 update

# 2024-12-27T18:03:47 update

# 2025-01-03T09:46:58 update

# 2025-01-20T08:28:48 update

# 2025-02-21T20:23:27 update

# 2025-04-25T13:08:47 update

# 2025-06-11T20:55:12 update

# 2025-06-16T17:35:40 update

# 2025-08-01T19:25:37 update

# 2025-08-27T20:53:40 update

# 2026-01-15T13:31:14 update

# 2026-02-06T16:29:56 update

# 2026-04-02T10:52:38 update
