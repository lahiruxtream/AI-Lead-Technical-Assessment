import secrets
from collections.abc import Callable
from typing import Any

import uvicorn
from mcp.server.fastmcp import FastMCP

from app.config import get_settings

DATA = {
    "employee_directory": {"payments_on_call": "Nimal Perera", "extension": "4421"},
    "service_catalog": {"payments-api": {"owner": "Payments Platform", "tier": 1, "channel": "#pay-ops"}},
    "incident_records": {"open_sev1": 0, "open_sev2": 1},
}

mcp = FastMCP(
    "Enterprise Data MCP",
    instructions="Read-only, synthetic enterprise directory, catalog, and incident data.",
    host=get_settings().mcp_bind_host,
    port=8010,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    max_request_body_size=16_384,
)


@mcp.tool()
async def get_enterprise_resource(resource: str) -> dict[str, Any]:
    """Read an allowlisted synthetic enterprise resource by name."""
    if resource not in DATA:
        raise ValueError("Unsupported enterprise resource")
    return {"source": "enterprise-mcp", "data": DATA[resource]}


class SharedSecretMiddleware:
    """Protect MCP HTTP transport with an internal shared secret."""

    def __init__(self, wrapped_app: Callable[..., Any]) -> None:
        self.wrapped_app = wrapped_app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            supplied = headers.get(b"x-mcp-key", b"").decode(errors="ignore")
            expected = get_settings().mcp_shared_secret.get_secret_value()
            if not secrets.compare_digest(supplied, expected):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": b'{"detail":"Unauthorized"}'})
                return
        await self.wrapped_app(scope, receive, send)


app = SharedSecretMiddleware(mcp.streamable_http_app())


if __name__ == "__main__":
    uvicorn.run(app, host=get_settings().mcp_bind_host, port=8010)
