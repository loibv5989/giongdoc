"""ASGI application composition for the KokoroTTS UI and API."""

from kokorotts.api import RUNTIME, api, status as runtime_status
from kokorotts.mcp_server import attach_mcp
from kokorotts.standalone_ui.server import create_app as create_ui_app
from kokorotts.standalone_ui.magic_api import attach_magic
from kokorotts.standalone_ui.script_api import attach_scripts
from kokorotts.standalone_ui.admin import attach_admin
from kokorotts.standalone_ui.server import _locale_manifest
from kokorotts.standalone_ui.web_gateway import BrowserSessions, WebGateway

app = create_ui_app(api_app=attach_mcp(api_app=api))
attach_magic(app)
attach_scripts(app, RUNTIME.settings.path.parent / "scripts")
admin_store = attach_admin(app, runtime=RUNTIME, status_provider=runtime_status)
app.add_middleware(
    WebGateway, sessions=BrowserSessions(RUNTIME.settings.path.with_name("web-session.key")), admin_store=admin_store,
    page_paths={"/", *(locale["path"] for locale in _locale_manifest()["locales"])}, schema_provider=app.openapi,
)

__all__ = ["app"]
