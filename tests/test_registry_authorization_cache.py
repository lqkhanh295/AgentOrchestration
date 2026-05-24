from src.agent.registry import AgentRegistry


def test_resolve_rechecks_cached_authorization_after_permission_change():
    registry = AgentRegistry()
    agent_id = registry.register(
        "worker",
        "test.worker",
        config={"permissions": {"alice": ["execute"]}},
    )

    assert registry.resolve(agent_id, principal="alice")["id"] == agent_id

    assert registry.set_permissions(agent_id, {"alice": []})
    assert registry.resolve(agent_id, principal="alice") is None

    audit_actions = [
        entry["action"] for entry in registry.authorization_audit()
    ]
    assert "authorization_denied" in audit_actions


def test_resolve_returns_copy_and_does_not_reuse_stale_cache_entry():
    registry = AgentRegistry()
    agent_id = registry.register(
        "worker",
        "test.worker",
        config={"permissions": {"alice": ["execute"], "bob": ["execute"]}},
    )

    resolved = registry.resolve(agent_id, principal="alice")
    resolved["name"] = "mutated"
    assert registry.resolve(agent_id, principal="alice")["name"] == "worker"

    registry.set_permissions(agent_id, {"bob": ["execute"]})

    assert registry.resolve(agent_id, principal="alice") is None
    assert registry.resolve(agent_id, principal="bob")["id"] == agent_id


def test_authorization_audit_omits_runtime_payloads():
    registry = AgentRegistry()
    agent_id = registry.register(
        "worker",
        "test.worker",
        config={
            "permissions": {"alice": ["execute"]},
            "runtime_payload": {"secret": "do-not-copy"},
        },
    )

    assert registry.resolve(agent_id, principal="mallory") is None

    audit = registry.authorization_audit()
    assert audit[-1]["action"] == "authorization_denied"
    assert "do-not-copy" not in str(audit)
