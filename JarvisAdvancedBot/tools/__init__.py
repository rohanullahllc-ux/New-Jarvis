"""Everything Jarvis can do, written once and shared by both brains (Claude and the free LocalBrain).

Each domain module holds its own ``TOOLS`` list; this package joins them and also exposes every tool by name,
so callers can write ``tools.get_weather("London")``.
"""
from . import info, productivity, space, web, windows, world
from .info import weather_report

TOOLS = [*info.TOOLS, *web.TOOLS, *windows.TOOLS, *productivity.TOOLS, *space.TOOLS, *world.TOOLS]

_names = []
for _tool in TOOLS:
    if _tool.name in _names:
        raise RuntimeError(f"Two tools are both called {_tool.name}.")
    _names.append(_tool.name)
    globals()[_tool.name] = _tool

__all__ = ["TOOLS", "weather_report", *_names]
