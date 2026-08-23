"""Vision is opt-in wiring: with VISION_SIDECAR_URL unset the toolsets and
prompts are byte-identical to the pre-vision agent; set, the scan agent
(discovery pass only, D-V9) gains check_images and the scan prompt gains the
photo block — except for repro-tolerant watches, which skip the pipeline
entirely."""

import asyncio
from contextlib import asynccontextmanager

from prompt import generate_prompt
from tools import check_images, disable_listing, save_price_check

import agent


def _prompt(**overrides) -> str:
    args = {
        "watch_id": 1,
        "site_id": 2,
        "site_name": "TestBay",
        "item_id": 3,
        "item_name": "Widget",
        "base_url": "https://example.test",
        "criteria": None,
        "selection_mode": "cheapest",
        "max_listings": 3,
        "allow_reproductions": False,
        **overrides,
    }
    return asyncio.run(generate_prompt(**args))


def test_prompt_is_byte_identical_when_vision_is_off():
    assert _prompt() == _prompt(vision_enabled=False)
    assert "PHOTO AUTHENTICITY CHECK" not in _prompt()
    assert "check_images" not in _prompt()


def test_prompt_gains_the_photo_block_when_vision_is_on():
    prompt = _prompt(vision_enabled=True)
    assert "PHOTO AUTHENTICITY CHECK" in prompt
    assert "check_images" in prompt
    assert "watch_id=1" in prompt
    # the D-V5 asymmetry wording rides along
    assert "reassurance ONLY" in prompt


def test_repro_tolerant_watches_skip_the_pipeline_entirely():
    prompt = _prompt(vision_enabled=True, allow_reproductions=True)
    assert "PHOTO AUTHENTICITY CHECK" not in prompt
    assert "check_images" not in prompt
    # …and are byte-identical to the pre-vision repro prompt
    assert prompt == _prompt(vision_enabled=False, allow_reproductions=True)


class _FakeMCP:
    """Stands in for MultiServerMCPClient — no server, no tools."""

    def __init__(self, *args, **kwargs):
        pass

    @asynccontextmanager
    async def session(self, server_name):
        yield None


async def _no_tools(session):
    return []


def _built_toolsets(monkeypatch, url) -> list:
    """Enter build_pass_agents with the LLM/MCP seams faked; the tool lists
    handed to create_agent, in call order (recheck first, scan second)."""
    toolsets = []
    monkeypatch.setattr(agent, "MultiServerMCPClient", _FakeMCP)
    monkeypatch.setattr(agent, "load_mcp_tools", _no_tools)
    monkeypatch.setattr(
        agent, "create_agent", lambda llm, tools: toolsets.append(tools) or object()
    )
    monkeypatch.setattr(agent, "VISION_SIDECAR_URL", url)

    async def build():
        async with agent.build_pass_agents():
            pass

    asyncio.run(build())
    return toolsets


def test_tool_absent_everywhere_when_url_unset(monkeypatch):
    recheck_tools, scan_tools = _built_toolsets(monkeypatch, None)
    assert check_images not in scan_tools
    assert check_images not in recheck_tools
    assert save_price_check in scan_tools  # the seam still built real toolsets


def test_tool_registered_on_the_scan_agent_only(monkeypatch):
    recheck_tools, scan_tools = _built_toolsets(monkeypatch, "http://vision.test")
    assert check_images in scan_tools
    assert check_images not in recheck_tools  # discovery pass only (D-V9)
    assert disable_listing in recheck_tools
