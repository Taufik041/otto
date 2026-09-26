from brain.tools import TOOLS, KIND
from runner.handlers import REGISTRY


def test_every_tool_has_a_kind():
    for t in TOOLS:
        assert t["function"]["name"] in KIND


def test_every_kind_has_a_handler():
    for kind in KIND.values():
        assert kind in REGISTRY
