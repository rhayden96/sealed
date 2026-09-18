import asyncio
from types import SimpleNamespace

import pytest

from sealed_agent import planner
from sealed_agent.domain import construct_draft


def failed_redis(tools):
    draft = construct_draft(tools.store, tools.catalog, catalog_id="redis_down", target="redis", environment="demo")
    tools.store.add_seal(draft=draft, verdict="aborted")


def enable_provider(monkeypatch):
    monkeypatch.setenv("PLANNER", "llama")
    monkeypatch.setenv("ALLOW_PLANNER_NETWORK", "true")
    monkeypatch.setenv("LLM_BASE_URL", "http://llama:11434/v1")


class Message:
    def __init__(self, calls=None, content=None):
        self.tool_calls = [SimpleNamespace(id=f"call-{index}", function=SimpleNamespace(name=name, arguments=arguments)) for index, (name, arguments) in enumerate(calls or [])]
        self.content = content

    def model_dump(self, **_):
        return {"role": "assistant", "content": self.content, "tool_calls": [
            {"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}
            for call in self.tool_calls
        ]}


def provider_script(monkeypatch, script):
    """All requests are in-process; no provider socket or real key is used."""
    import openai

    requests = []
    script = iter(script)

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["timeout"] <= planner.PROPOSAL_TIMEOUT_S
            self.chat = SimpleNamespace(completions=self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def create(self, **kwargs):
            requests.append(kwargs)
            event = next(script)
            if isinstance(event, BaseException):
                raise event
            return SimpleNamespace(choices=[SimpleNamespace(message=event)])

    monkeypatch.setattr(openai, "AsyncOpenAI", Client)
    return requests


def test_stub_authoritative_even_with_provider_credentials(agent_tools, monkeypatch):
    import openai

    monkeypatch.setenv("XAI_API_KEY", "inherited-test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://llama:11434/v1")
    monkeypatch.setenv("ALLOW_PLANNER_NETWORK", "true")
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: pytest.fail("stub attempted provider request"))
    failed_redis(agent_tools)
    result = asyncio.run(planner.propose(agent_tools))
    assert result["requested_provider"] == result["actual_provider"] == "stub"
    assert result["fallback_reason"] is None
    assert result["draft"]["status"] == "draft"


def test_external_provider_disabled_without_opt_in(agent_tools, monkeypatch):
    monkeypatch.setenv("PLANNER", "xai")
    monkeypatch.delenv("ALLOW_PLANNER_NETWORK", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "inherited-test-key")
    result = asyncio.run(planner.propose(agent_tools))
    assert result["requested_provider"] == "xai"
    assert result["actual_provider"] == "stub"
    assert result["fallback_reason"] == "planner_network_disabled"


@pytest.mark.parametrize("raw", ['{', '[]', '{"duration_s":NaN}', '{"x":1,"x":2}', '"' + 'x' * 16384 + '"'])
def test_malformed_arguments_rejected(raw):
    with pytest.raises(ValueError):
        planner.parse_arguments(raw)


@pytest.mark.parametrize("call", [
    ("shell", '{}'), ("propose_experiment", '{"catalog_id":"worker_drop","target":"worker","unseal":true}'),
    ("get_run", '{"draft_id":42}'), ("list_experiments", '{"unexpected":true}'),
    ("propose_experiment", '{"catalog_id":"worker_drop","target":"worker","params":{"drop_rate":2}}'),
])
def test_bad_model_tools_fall_back_honestly_without_mutations(agent_tools, monkeypatch, call):
    enable_provider(monkeypatch)
    requests = provider_script(monkeypatch, [Message([call])])
    result = asyncio.run(planner.propose(agent_tools))
    assert result["actual_provider"] == "stub"
    assert result["requested_provider"] == "llama"
    assert result["fallback_reason"].startswith("provider_failure:")
    assert agent_tools.store.list_drafts() == []
    assert len(requests) == 1


def test_duplicate_model_proposal_and_retry_use_one_identity(agent_tools, monkeypatch):
    enable_provider(monkeypatch)
    call = ("propose_experiment", '{"catalog_id":"worker_drop","target":"worker"}')
    requests = provider_script(monkeypatch, [Message([call, call]), Message(content="Draft proposed.")])
    first = asyncio.run(planner.propose(agent_tools, proposal_id="retry-1"))
    second = asyncio.run(planner.propose(agent_tools, proposal_id="retry-1"))
    assert first["draft"]["id"] == second["draft"]["id"]
    assert first["actual_provider"] == second["actual_provider"] == "llama"
    assert second["outcome"] == "existing_proposal"
    assert len(agent_tools.store.list_drafts()) == 1
    assert len(requests) == 2


def test_provider_failure_after_saved_draft_preserves_partial_result(agent_tools, monkeypatch):
    enable_provider(monkeypatch)
    provider_script(monkeypatch, [
        Message([("propose_experiment", '{"catalog_id":"worker_drop","target":"worker"}')]),
        RuntimeError("url?api_key=do-not-disclose"),
    ])
    result = asyncio.run(planner.propose(agent_tools))
    assert result["outcome"] == "partial_failure"
    assert result["actual_provider"] == "llama"
    assert result["fallback_reason"] == "provider_failure:RuntimeError"
    assert "do-not-disclose" not in str(result)
    assert result["draft"]["status"] == "draft"
    assert len(agent_tools.store.list_drafts()) == 1


def test_provider_deadline_and_cancellation_do_not_block_event_loop(agent_tools, monkeypatch):
    enable_provider(monkeypatch)
    monkeypatch.setattr(planner, "PROPOSAL_TIMEOUT_S", .05)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow(_):
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    monkeypatch.setattr(planner, "llm_propose", slow)

    async def check():
        task = asyncio.create_task(planner.propose(agent_tools))
        await entered.wait()
        ticks = 0
        while not task.done():
            await asyncio.sleep(.005)
            ticks += 1
        assert ticks >= 2
        assert cancelled.is_set()
        return await task

    result = asyncio.run(check())
    assert result["fallback_reason"] == "proposal_timeout"
    assert result["actual_provider"] == "stub"


def test_caller_cancellation_propagates(agent_tools, monkeypatch):
    enable_provider(monkeypatch)
    entered = asyncio.Event()

    async def slow(_):
        entered.set()
        await asyncio.sleep(10)

    monkeypatch.setattr(planner, "llm_propose", slow)

    async def check():
        task = asyncio.create_task(planner.propose(agent_tools))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert agent_tools.store.list_drafts() == []

    asyncio.run(check())


def test_provider_metadata_cannot_revert_concurrent_approval(agent_tools, monkeypatch):
    enable_provider(monkeypatch)

    async def provider(tools):
        draft = tools.call("propose_experiment", catalog_id="worker_drop", target="worker")
        current = tools.store.get_draft(draft["id"])
        current.update(approved=True, status="approved")
        tools.store.put_draft(current)
        raise RuntimeError("later failure")

    monkeypatch.setattr(planner, "llm_propose", provider)
    result = asyncio.run(planner.propose(agent_tools))
    assert result["draft"]["approved"] is True
    assert result["draft"]["status"] == "approved"
