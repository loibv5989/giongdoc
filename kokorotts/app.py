"""ASGI application composition for the KokoroTTS UI and API."""

from kokorotts.api import RUNTIME, api, status as runtime_status
from kokorotts.mcp_server import attach_mcp
from kokorotts.standalone_ui.server import create_app as create_ui_app
from kokorotts.standalone_ui.magic_api import attach_magic
from kokorotts.standalone_ui.script_api import attach_scripts
from kokorotts.standalone_ui.admin import attach_admin

app = create_ui_app(api_app=attach_mcp(api_app=api))
attach_magic(app)
attach_scripts(app, RUNTIME.settings.path.parent / "scripts")
attach_admin(app, runtime=RUNTIME, status_provider=runtime_status)

__all__ = ["app"]
