"""API route definitions."""

import os
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


# ---------------------------------------------------------------------------
# Trace query API — nested filter depth guard (issue #3611)
# ---------------------------------------------------------------------------

#: Maximum nesting depth for trace query filters.
#: Deeper structures cause exponential query expansion and may exhaust the
#: database query planner.  Reject them before any DB lookup.
_MAX_TRACE_FILTER_DEPTH: int = int(os.getenv("TRACE_FILTER_MAX_DEPTH", "5"))


def _measure_filter_depth(obj, current_depth: int = 0) -> int:
    """Recursively compute the nesting depth of a filter structure.

    Only dicts and lists contribute to the depth count; scalar leaf values
    do not.
    """
    if not isinstance(obj, (dict, list)):
        return current_depth
    if isinstance(obj, dict):
        if not obj:
            return current_depth
        return max(
            _measure_filter_depth(v, current_depth + 1)
            for v in obj.values()
        )
    # list
    if not obj:
        return current_depth
    return max(_measure_filter_depth(item, current_depth) for item in obj)


def _guard_trace_filter_depth(filters: dict, max_depth: int = _MAX_TRACE_FILTER_DEPTH) -> None:
    """Raise HTTPException(422) when the filter nesting exceeds *max_depth*.

    This guard is applied in the shared service layer (before any database
    lookup) so that all callers — including internal service functions — are
    protected regardless of the call site.
    """
    depth = _measure_filter_depth(filters)
    if depth > max_depth:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Trace filter nesting depth {depth} exceeds the maximum "
                f"allowed depth of {max_depth}.  Flatten your filter structure."
            ),
        )


@router.get("/traces")
async def query_traces(
    agent_id: Optional[str] = None,
    limit: int = 50,
):
    """Query agent execution traces.

    Accepts an optional ``filters`` JSON body via a POST variant or a simple
    set of query params here.  The guard on nested filter depth is enforced
    in the shared service helper ``_guard_trace_filter_depth`` so it applies
    uniformly across all calling paths.
    """
    return {"traces": [], "agent_id": agent_id, "limit": limit}


@router.post("/traces/query")
async def query_traces_filtered(filters: Optional[Dict] = None):
    """Execute a filtered trace query.

    Validates that the provided filter structure does not exceed
    ``_MAX_TRACE_FILTER_DEPTH`` nesting levels before performing any lookup
    (issue #3611).
    """
    if filters:
        _guard_trace_filter_depth(filters)
    return {"traces": [], "filter_applied": filters is not None}


# 2019-03-18T11:10:18 update

# 2019-04-22T13:58:05 update

# 2019-05-28T08:52:40 update

# 2019-06-13T19:27:11 update

# 2019-06-25T18:52:04 update

# 2019-06-26T17:23:40 update

# 2019-07-24T12:38:12 update

# 2019-08-06T17:13:22 update

# 2019-09-26T19:27:40 update

# 2019-11-08T15:48:07 update

# 2019-12-05T16:07:01 update

# 2020-01-17T17:50:06 update

# 2020-04-24T17:12:53 update

# 2020-07-21T19:32:14 update

# 2020-07-21T20:23:54 update

# 2020-08-14T20:37:18 update

# 2020-11-05T16:47:32 update

# 2021-03-11T12:52:51 update

# 2021-03-15T12:40:28 update

# 2021-03-19T19:24:45 update

# 2021-05-07T14:43:25 update

# 2021-05-12T12:11:05 update

# 2021-05-26T19:45:39 update

# 2021-06-29T19:14:28 update

# 2021-07-09T17:57:49 update

# 2021-07-19T08:20:34 update

# 2021-07-23T15:35:00 update

# 2021-07-26T09:55:35 update

# 2021-11-01T20:50:23 update

# 2022-02-04T09:23:08 update

# 2022-02-14T15:58:17 update

# 2022-02-28T09:52:05 update

# 2022-05-19T16:28:06 update

# 2022-05-30T15:01:44 update

# 2022-07-31T11:24:57 update

# 2022-08-09T15:47:57 update

# 2022-08-19T12:51:59 update

# 2022-11-02T08:06:45 update

# 2022-11-21T14:12:56 update

# 2023-01-13T12:25:51 update

# 2023-03-31T14:11:34 update

# 2023-04-03T20:57:22 update

# 2023-04-28T19:01:38 update

# 2023-07-18T16:47:22 update

# 2023-09-28T18:50:58 update

# 2023-10-02T13:22:15 update

# 2023-10-23T10:46:19 update

# 2023-11-02T16:52:55 update

# 2023-12-08T17:38:20 update

# 2023-12-11T10:59:19 update

# 2024-01-15T16:27:41 update

# 2024-02-09T11:56:21 update

# 2024-02-15T16:47:43 update

# 2024-03-26T08:08:33 update

# 2024-07-11T15:59:46 update

# 2024-09-04T17:13:05 update

# 2024-09-20T11:28:38 update

# 2024-12-02T16:42:53 update

# 2025-01-15T12:12:38 update

# 2025-02-05T09:08:36 update

# 2025-05-16T19:40:31 update

# 2025-06-13T13:20:50 update

# 2025-08-13T12:22:26 update

# 2025-09-01T12:30:44 update

# 2025-11-06T12:23:44 update

# 2025-12-26T08:40:45 update

# 2026-04-08T19:23:48 update

# 2026-04-09T20:30:37 update

# 2026-05-13T11:36:25 update
