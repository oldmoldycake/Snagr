"""Vision is opt-in wiring: with VISION_SIDECAR_URL unset the toolsets and
prompts carry no photo check; set, the hunt agent (never the
recheck agent) gains check_images and the hunt prompt gains the
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
    # the ids are bound on the run config, never typed by the model
    assert "watch_id=" not in prompt
    # the evidence-asymmetry wording (fakes condemn, reals barely reassure) rides along
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


class _BrowserTool:
    """The MCP tools the session hands back. open_browser_session reaches for
    two of them by name to build its PageReader, and filters the rest by
    name; nothing calls them here."""

    def __init__(self, name):
        self.name = name


MCP_TOOLS = [
    "browser_navigate",
    "browser_evaluate",
    "browser_snapshot",
    "browser_run_code_unsafe",
    "browser_file_upload",
    "browser_tabs",
]


async def _browser_tools(session):
    return [_BrowserTool(name) for name in MCP_TOOLS]


def _name(tool) -> str:
    """MCP tools carry a name; the guarded navigate wrapper is a plain
    function, and langchain names that one after the function."""
    return getattr(tool, "name", None) or tool.__name__


def _open_session(monkeypatch, url=None):
    """Enter open_browser_session with the MCP seam faked."""
    monkeypatch.setattr(agent, "MultiServerMCPClient", _FakeMCP)
    monkeypatch.setattr(agent, "load_mcp_tools", _browser_tools)
    monkeypatch.setattr(agent, "VISION_SIDECAR_URL", url)
    built = []

    async def build():
        async with agent.open_browser_session() as opened:
            built.append(opened)

    asyncio.run(build())
    return built[0]


def _built_toolsets(monkeypatch, url) -> tuple[list, list]:
    """The tool lists handed to create_agent, recheck first, hunt second."""
    toolsets = []
    monkeypatch.setattr(
        agent, "create_agent", lambda llm, tools, **_: toolsets.append(tools) or object()
    )
    browser_tools, _ = _open_session(monkeypatch, url)
    agent.build_recheck_agent("llm", browser_tools)
    agent.build_hunt_agent("llm", browser_tools)
    return toolsets[0], toolsets[1]


def test_tool_absent_everywhere_when_url_unset(monkeypatch):
    recheck_tools, hunt_tools = _built_toolsets(monkeypatch, None)
    assert check_images not in hunt_tools
    assert check_images not in recheck_tools
    assert save_price_check in hunt_tools  # the seam still built real toolsets


def test_tool_registered_on_the_hunt_agent_only(monkeypatch):
    recheck_tools, hunt_tools = _built_toolsets(monkeypatch, "http://vision.test")
    assert check_images in hunt_tools
    assert check_images not in recheck_tools  # hunts only
    assert disable_listing in recheck_tools


def test_the_hunt_agent_can_disable_a_listing_it_finds_already_sold(monkeypatch):
    # the hunt prompt tells the model to follow a sold/ended save_price_check
    # with disable_listing, so the tool must be registered on the hunt agent.
    _, hunt_tools = _built_toolsets(monkeypatch, None)

    assert disable_listing in hunt_tools


def test_the_page_reader_is_built_from_the_sessions_browser_tools(monkeypatch):
    # what lets code drive the same browser the model is using, with no
    # tokens spent and no model in the loop
    _, browser = _open_session(monkeypatch)

    assert isinstance(browser, agent.PageReader)


def test_the_model_never_gets_the_dangerous_browser_tools(monkeypatch):
    # nothing a price scraper does needs arbitrary JS, a file picker, or
    # windows the orchestrator is not watching
    browser_tools, _ = _open_session(monkeypatch)

    offered = {_name(tool) for tool in browser_tools}
    assert offered & agent.BLOCKED_BROWSER_TOOLS == set()
    assert "browser_snapshot" in offered


def test_navigation_goes_through_the_url_guard(monkeypatch):
    # the model still gets a tool named browser_navigate, but it is the
    # guarded wrapper, not the MCP tool that goes anywhere it is pointed
    browser_tools, _ = _open_session(monkeypatch)

    navigate = next(tool for tool in browser_tools if _name(tool) == "browser_navigate")
    assert not isinstance(navigate, _BrowserTool)
