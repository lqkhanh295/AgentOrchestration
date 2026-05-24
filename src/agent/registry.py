"""Agent Registry — Manages agent lifecycle and metadata."""

from copy import deepcopy
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._auth_versions: Dict[str, int] = {}
        self._resolution_cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._authorization_audit: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        self._auth_versions[agent_id] = 0
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def set_permissions(
        self,
        agent_id: str,
        permissions: Dict[str, List[str]],
    ) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["config"]["permissions"] = deepcopy(permissions)
        self._auth_versions[agent_id] = (
            self._auth_versions.get(agent_id, 0) + 1
        )
        self._invalidate_resolution_cache(agent_id)
        self._record_authorization_audit(
            agent_id=agent_id,
            principal="system",
            permission="permissions:update",
            action="permissions_updated",
            reason="authorization policy changed",
        )
        return True

    def resolve(
        self,
        agent_id: str,
        principal: str = "",
        permission: str = "execute",
    ) -> Optional[Dict[str, Any]]:
        cache_key = (agent_id, principal, permission)
        current_version = self._auth_versions.get(agent_id, 0)
        cached = self._resolution_cache.get(cache_key)
        if cached:
            agent = self._agents.get(agent_id)
            cache_is_current = cached["auth_version"] == current_version
            if (
                agent
                and cache_is_current
                and self._is_authorized(agent, principal, permission)
            ):
                return deepcopy(cached["agent"])
            self._resolution_cache.pop(cache_key, None)
            self._record_authorization_audit(
                agent_id=agent_id,
                principal=principal,
                permission=permission,
                action="cached_resolution_rejected",
                reason="authorization changed or no longer allows access",
            )

        agent = self._agents.get(agent_id)
        if not agent:
            return None
        if not self._is_authorized(agent, principal, permission):
            self._record_authorization_audit(
                agent_id=agent_id,
                principal=principal,
                permission=permission,
                action="authorization_denied",
                reason="principal lacks requested permission",
            )
            return None

        resolved = deepcopy(agent)
        self._resolution_cache[cache_key] = {
            "agent": resolved,
            "auth_version": current_version,
        }
        return deepcopy(resolved)

    def authorization_audit(self) -> List[Dict[str, Any]]:
        return deepcopy(self._authorization_audit)

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._auth_versions.pop(agent_id, None)
        self._invalidate_resolution_cache(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def _invalidate_resolution_cache(self, agent_id: str) -> None:
        stale_keys = [
            cache_key
            for cache_key in self._resolution_cache
            if cache_key[0] == agent_id
        ]
        for cache_key in stale_keys:
            self._resolution_cache.pop(cache_key, None)

    def _is_authorized(
        self,
        agent: Dict[str, Any],
        principal: str,
        permission: str,
    ) -> bool:
        if not principal:
            return True
        permissions = agent.get("config", {}).get("permissions")
        if not permissions:
            return True
        allowed = permissions.get(principal, [])
        return "*" in allowed or permission in allowed

    def _record_authorization_audit(
        self,
        *,
        agent_id: str,
        principal: str,
        permission: str,
        action: str,
        reason: str,
    ) -> None:
        self._authorization_audit.append(
            {
                "agent_id": agent_id,
                "principal": principal,
                "permission": permission,
                "action": action,
                "reason": reason,
                "auth_version": self._auth_versions.get(agent_id, 0),
                "recorded_at": time.time(),
            }
        )

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
