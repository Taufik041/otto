import json

import pytest

from shared import config
from tests.fakes import use_env


def test_numbered_keys_in_order_and_empty_ones_skipped():
    env = {"OPENROUTER_API_KEY3": "k3", "OPENROUTER_API_KEY": "k1", "OPENROUTER_API_KEY2": "  ",
           "OPENROUTER_API_KEY10": "k10", "OPENROUTER_API_KEY4": "", "OPENROUTER_API_KEYX": "nope",
           "OTHER_OPENROUTER_API_KEY5": "nope"}
    assert config.numbered_keys(env, "OPENROUTER_API_KEY") == ["k1", "k3", "k10"]


def test_duplicate_keys_count_once():
    env = {"OPENROUTER_API_KEY": "k1", "OPENROUTER_API_KEY2": "k1", "OPENROUTER_API_KEY3": "k3"}
    assert config.numbered_keys(env, "OPENROUTER_API_KEY") == ["k1", "k3"]


def test_provider_keys():
    env = {"OPENROUTER_API_KEY": "a", "OPENROUTER_API_KEY2": "b", "OPENAI_API_KEY": "c",
           "OPENAI_API_KEY2": "ignored: openai takes one key", "OTTO_API_KEY": "d"}
    assert config.provider_keys(env) == {"openrouter": ["a", "b"], "openai": ["c"], "custom": ["d"]}
    assert config.provider_keys({"API_KEY": "e"})["custom"] == ["e"]
    assert config.provider_keys({"OPENAI_API_KEY": ""}) == {"openrouter": [], "openai": [], "custom": []}


FREE = {"id": "openrouter:openrouter/free", "provider": "openrouter", "model": "openrouter/free",
        "label": "OpenRouter", "description": "Good for small tasks"}


def test_default_catalog_has_no_invented_openai_models():
    assert config.model_catalog({"OPENAI_API_KEY": "c"}) == [FREE]


def test_openai_models_come_from_env():
    catalog = config.model_catalog({"OTTO_OPENAI_MODELS": " model-a, ,model-b "})
    assert catalog == [FREE,
                       {"id": "openai:model-a", "provider": "openai", "model": "model-a", "label": "OpenAI model-a"},
                       {"id": "openai:model-b", "provider": "openai", "model": "model-b", "label": "OpenAI model-b"}]


def test_custom_provider_is_listed_when_configured():
    catalog = config.model_catalog({"OTTO_API_KEY": "d", "OTTO_MODEL": "some/model"})
    assert catalog[-1] == {"id": "custom:some/model", "provider": "custom", "model": "some/model",
                           "label": "Custom some/model"}
    assert all(m["provider"] != "custom" for m in config.model_catalog({}))


def test_otto_models_replaces_the_catalog():
    models = [{"id": "fast", "provider": "openrouter", "model": "x/y:free"},
              {"id": "big", "provider": "openai", "model": "m", "label": "Big", "description": "Best for larger changes"}]
    catalog = config.model_catalog({"OTTO_MODELS": json.dumps(models), "OTTO_OPENAI_MODELS": "ignored"})
    assert catalog == [{"id": "fast", "provider": "openrouter", "model": "x/y:free", "label": "fast"},
                       {"id": "big", "provider": "openai", "model": "m", "label": "Big",
                        "description": "Best for larger changes"}]


@pytest.mark.parametrize("bad", [
    "not json", "{}", "[1]", '[{"id": "a", "provider": "nope", "model": "m"}]',
    '[{"id": "a", "provider": "openai"}]',
    '[{"id": "a", "provider": "openai", "model": "m"}, {"id": "a", "provider": "openai", "model": "n"}]',
])
def test_bad_otto_models_is_a_clear_error(bad):
    with pytest.raises(ValueError, match="OTTO_MODELS"):
        config.model_catalog({"OTTO_MODELS": bad})


def test_availability_and_default_depend_on_keys(monkeypatch):
    use_env(monkeypatch, {"OTTO_OPENAI_MODELS": "model-a"})
    assert not config.is_available("openrouter:openrouter/free")
    assert not config.is_available("openai:model-a")
    assert config.DEFAULT_MODEL is None

    use_env(monkeypatch, {"OTTO_OPENAI_MODELS": "model-a", "OPENAI_API_KEY": "c"})
    assert not config.is_available("openrouter:openrouter/free")
    assert config.is_available("openai:model-a")
    assert config.DEFAULT_MODEL == "openai:model-a"  # the first available one

    use_env(monkeypatch, {"OTTO_OPENAI_MODELS": "model-a", "OPENAI_API_KEY": "c", "OPENROUTER_API_KEY2": "b"})
    assert config.is_available("openrouter:openrouter/free")
    assert config.DEFAULT_MODEL == "openrouter:openrouter/free"
    assert not config.is_available("openai:not-in-catalog")


def test_default_model_env_wins(monkeypatch):
    use_env(monkeypatch, {"OTTO_OPENAI_MODELS": "model-a", "OPENAI_API_KEY": "c", "OPENROUTER_API_KEY": "b",
                          "OTTO_DEFAULT_MODEL": "openai:model-a"})
    assert config.DEFAULT_MODEL == "openai:model-a"


def test_resolve_model(monkeypatch):
    use_env(monkeypatch, {"OPENROUTER_API_KEY": "b", "OTTO_OPENAI_MODELS": "model-a"})
    assert config.resolve_model("openai:model-a") == {
        "id": "openai:model-a", "provider": "openai", "model": "model-a", "label": "OpenAI model-a"}
    # a session keeps its model even if the catalog changed since it was created
    assert config.resolve_model("openrouter:meta/llama:free")["provider"] == "openrouter"
    assert config.resolve_model("openrouter:meta/llama:free")["model"] == "meta/llama:free"
    # rows from before providers stored a bare model name, used with OTTO_BASE_URL/OTTO_API_KEY
    assert config.resolve_model("openrouter/free")["provider"] == "openrouter"
    use_env(monkeypatch, {"OTTO_API_KEY": "d"})
    assert config.resolve_model("openrouter/free") == {
        "id": "openrouter/free", "provider": "custom", "model": "openrouter/free", "label": "openrouter/free"}


def test_the_default_daily_limit_is_300k(monkeypatch):
    import importlib
    monkeypatch.delenv("DAILY_TOKEN_LIMIT", raising=False)
    try:
        assert importlib.reload(config).DAILY_TOKEN_LIMIT == 300_000
    finally:
        importlib.reload(config)
