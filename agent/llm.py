"""The chat model, built when something actually needs one.

Not a module-level `init_chat_model(...)`: the check pool re-reads most
listings with no model in the loop at all, and it should not pay for one — or
fail to start because the provider is misconfigured — just to open a browser.

A factory, not a cached singleton: the client is cheap to build, the pools are
few, and a provider whose key rotated is then fixed by the next job rather
than by a restart.

Tracing lives here too, because every model call is traced the same way
whichever pool made it. LangSmith traces globally on its own when
LANGSMITH_TRACING/LANGSMITH_API_KEY are set; Langfuse hooks in per call, so
its handler rides on each call's config and is only built when keys are
configured.

The hunter never stops, so a tracing session is not a run: it is the thing
being watched over time — one watch for hunts and rechecks, one item for
grounding — and a trace is one job inside it. Everything else a trace might
be sliced by (job kind, site, category) is a tag, because a trace sits in
exactly one session but can carry any number of tags.
"""

from contextlib import contextmanager

from config import AI_API_KEY, AI_MODEL, AI_PROVIDER, AI_URL, LANGFUSE_ENABLED
from langchain.chat_models import init_chat_model
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

callbacks = [CallbackHandler()] if LANGFUSE_ENABLED else []


def build_llm():
    """A chat model for the configured provider (AI_PROVIDER / AI_MODEL)."""
    if AI_API_KEY:
        return init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL, api_key=AI_API_KEY)
    return init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL)


@contextmanager
def job_trace(name: str, session_id: str, tags: list[str], **ids: int):
    """
    Open one trace for a job made of bare model calls, and hold it open while
    the job runs.

    Every call made inside nests under a span named after the job, and the
    session, tags and ids are propagated to all of them — so a job's calls
    read as one trace, as an agent run's do, rather than as separate traces
    with nothing grouping them: the Langfuse handler only turns langfuse_*
    metadata into trace attributes when the outermost run is a chain, which
    an agent run is and a bare `llm.ainvoke` is not. Each call still needs
    `callbacks` in its config to be recorded at all. Does nothing unless
    Langfuse is configured.

    Args:
      name: The trace name — the job kind.
      session_id: The thing the job is about, e.g. "item-7".
      tags: Filterable labels, e.g. ["kind:ground", "category:video-games"].
      ids: The job and the ids it is bound to, copied into trace metadata.
    """
    if not LANGFUSE_ENABLED:
        yield
        return
    metadata = {key: str(value) for key, value in ids.items()}
    with (
        propagate_attributes(trace_name=name, session_id=session_id, tags=tags, metadata=metadata),
        get_client().start_as_current_observation(as_type="span", name=name),
    ):
        yield


def flush_traces() -> None:
    """Langfuse queues events on a background thread; flush them where a job
    ends, or the tail of its traces is silently dropped."""
    if LANGFUSE_ENABLED:
        get_client().flush()
