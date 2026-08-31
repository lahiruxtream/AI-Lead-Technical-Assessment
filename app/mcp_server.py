import uvicorn
from fastapi import FastAPI

app = FastAPI(title="Dummy Enterprise MCP Data Service")
DATA = {
    "employee_directory": {"payments_on_call": "Nimal Perera", "extension": "4421"},
    "service_catalog": {"payments-api": {"owner": "Payments Platform", "tier": 1, "channel": "#pay-ops"}},
    "incident_records": {"open_sev1": 0, "open_sev2": 1},
}


@app.get("/resources/{resource}")
async def resource(resource: str):
    return {"source": "enterprise-mcp", "data": DATA.get(resource, {})}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8010)
