"""How a job's model calls land in Langfuse, recorded through the real
handler into an in-memory span exporter — nothing leaves the process.

What is pinned here is the handler's own behavior, which is easy to get
wrong: it only turns langfuse_* metadata into trace attributes when the
outermost run is a chain. An agent run is one, so a hunt or recheck can carry
its session and tags on its config; grounding makes bare model calls, which
is why it opens its trace with llm.job_trace instead."""

import asyncio

import llm
import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.runnables import RunnableLambda
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(scope="module")
def langfuse():
    """One client for the module: the SDK keeps one set of resources per
    public key, so a second client would never reach its own exporter."""
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        span_exporter=exporter,
    )
    yield client, exporter
    client.shutdown()


@pytest.fixture
def spans(langfuse, monkeypatch):
    """Langfuse switched on against an exporter the test can read. Yields a
    function returning the finished spans by name."""
    client, exporter = langfuse
    exporter.clear()
    monkeypatch.setattr(llm, "LANGFUSE_ENABLED", True)
    monkeypatch.setattr(llm, "get_client", lambda: client)
    monkeypatch.setattr(llm, "callbacks", [CallbackHandler(public_key="pk-lf-test")])

    def finished():
        client.flush()
        return {span.name: span for span in exporter.get_finished_spans()}

    return finished


def model():
    return FakeListChatModel(responses=["{}"] * 5)


class TestJobTrace:
    def test_a_jobs_bare_model_calls_share_one_trace_in_its_session(self, spans):
        async def ground():
            with llm.job_trace(
                "ground", "item-7", ["kind:ground", "category:games"], job_id=3, item_id=7
            ):
                for name in ("condition-tiers", "extract-observations"):
                    await model().ainvoke(
                        "prompt", config={"callbacks": llm.callbacks, "run_name": name}
                    )

        asyncio.run(ground())
        by_name = spans()

        root = by_name["ground"]
        assert root.parent is None
        for name in ("condition-tiers", "extract-observations"):
            call = by_name[name]
            assert call.context.trace_id == root.context.trace_id
            assert call.attributes["session.id"] == "item-7"
            assert call.attributes["langfuse.trace.name"] == "ground"
            assert call.attributes["langfuse.trace.tags"] == ("kind:ground", "category:games")
            assert call.attributes["langfuse.trace.metadata.job_id"] == "3"
            assert "user.id" not in call.attributes

    def test_a_bare_call_outside_one_does_not_join_the_session(self, spans):
        # why job_trace exists: the same keys on a bare call's config stay
        # plain metadata and group nothing
        metadata = {"langfuse_session_id": "item-7", "langfuse_tags": ["kind:ground"]}
        asyncio.run(
            model().ainvoke(
                "prompt",
                config={"callbacks": llm.callbacks, "run_name": "bare", "metadata": metadata},
            )
        )
        assert "session.id" not in spans()["bare"].attributes

    def test_an_agent_runs_config_keys_do_reach_the_trace(self, spans):
        metadata = {
            "langfuse_session_id": "watch-12",
            "langfuse_user_id": "3",
            "langfuse_tags": ["kind:hunt"],
        }
        asyncio.run(
            RunnableLambda(lambda prompt: prompt).ainvoke(
                "prompt",
                config={"callbacks": llm.callbacks, "run_name": "hunt", "metadata": metadata},
            )
        )
        hunt = spans()["hunt"]
        assert hunt.attributes["session.id"] == "watch-12"
        assert hunt.attributes["user.id"] == "3"
        assert hunt.attributes["langfuse.trace.tags"] == ("kind:hunt",)

    def test_without_langfuse_it_is_a_plain_block(self, monkeypatch):
        monkeypatch.setattr(llm, "LANGFUSE_ENABLED", False)

        def no_client():
            raise AssertionError("no Langfuse client without keys")

        monkeypatch.setattr(llm, "get_client", no_client)
        with llm.job_trace("ground", "item-7", ["kind:ground"], job_id=3):
            ran = True
        assert ran
