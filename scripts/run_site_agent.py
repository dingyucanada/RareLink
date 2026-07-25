"""Run one hospital-local RareLink Site Agent."""

from __future__ import annotations

import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rarelink.site_agent import SiteAgentSettings, create_site_agent_app  # noqa: E402


def main() -> None:
    settings = SiteAgentSettings()  # type: ignore[call-arg]
    app = create_site_agent_app(settings)
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.port,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
