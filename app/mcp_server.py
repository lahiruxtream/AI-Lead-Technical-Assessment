import secrets

import uvicorn
from fastapi import FastAPI, Header, HTTPException, status

from app.config import get_settings

app = FastAPI(title="Dummy Enterprise MCP Data Service")
DATA = {
    "employee_directory": {"payments_on_call": "Nimal Perera", "extension": "4421"},
    "service_catalog": {"payments-api": {"owner": "Payments Platform", "tier": 1, "channel": "#pay-ops"}},
    "incident_records": {"open_sev1": 0, "open_sev2": 1},
}


@app.get("/resources/{resource}")
async def resource(resource: str, x_mcp_key: str = Header(default="")):
    expected = get_settings().mcp_shared_secret.get_secret_value()
    if not secrets.compare_digest(x_mcp_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MCP credential")
    if resource not in DATA:
        raise HTTPException(status_code=404, detail="Resource not found")
    return {"source": "enterprise-mcp", "data": DATA.get(resource, {})}


if __name__ == "__main__":
    uvicorn.run(app, host=get_settings().mcp_bind_host, port=8010)
