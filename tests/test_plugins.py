import pytest

from agentic_data_platform.plugins import PluginManager


def test_plugin_hooks_are_ordered_and_failures_are_isolated():
    manager = PluginManager()
    manager.register("first", "tool.after", lambda payload: payload["value"] + 1)
    manager.register("broken", "tool.after", lambda payload: 1 / 0)
    manager.register("last", "tool.after", lambda payload: payload["value"] + 2)

    results = manager.emit("tool.after", {"value": 2})
    assert [item.plugin for item in results] == ["first", "broken", "last"]
    assert results[0].result == 3
    assert results[1].success is False
    assert "ZeroDivisionError" in results[1].error
    assert results[2].result == 4


def test_unknown_hook_is_rejected():
    manager = PluginManager()
    with pytest.raises(ValueError):
        manager.register("plugin", "unknown.hook", lambda payload: payload)
