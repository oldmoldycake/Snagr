"""The chat model, built when something actually needs one.

It used to be a module-level `init_chat_model(...)`, which meant importing the
orchestrator built a client whether or not a model would ever be called. Under
the daemon that is the wrong shape: the check pool re-reads most listings with
no model in the loop at all, and it should not pay for one — or fail to start
because the provider is misconfigured — just to open a browser.

A factory, not a cached singleton: the client is cheap to build, the pools are
few, and a provider whose key rotated is then fixed by the next job rather
than by a restart.
"""

from config import AI_API_KEY, AI_MODEL, AI_PROVIDER, AI_URL
from langchain.chat_models import init_chat_model


def build_llm():
    """A chat model for the configured provider (AI_PROVIDER / AI_MODEL)."""
    if AI_API_KEY:
        return init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL, api_key=AI_API_KEY)
    return init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL)
