# Security model

## Trust boundaries

- User input, retrieved documents, and MCP responses are untrusted.
- Role authorization is enforced inside every tool, not delegated to the LLM or routing prompt.
- Retrieval filters evidence by access level before text reaches the model.
- The analytics tool exposes predefined operations; it does not execute model-generated Python or use `eval`.

## Prompt injection and exfiltration

Requests matching instruction override, prompt disclosure, secret extraction, or RBAC bypass patterns are rejected. Instruction-like lines are removed from retrieved documents before they enter model context. The system prompt says evidence is data, not instruction, and generated output is checked for credential/private-key patterns. This layered approach reduces common attacks but pattern matching alone is not a complete production defense; add a dedicated classifier, DLP, output policy model, and red-team evaluation.

## Grounding and citations

The model is told to answer only from retrieved evidence and use `[document-id]` citations. A deterministic post-validator compares every citation to authorized retrieved IDs and strips invalid citations. Insufficient evidence produces an explicit non-answer.

## Brand safety

The assistant identifies as a Commercial Bank internal assistant, avoids unsupported financial claims, never advises disabling fraud controls, and does not expose credentials or customer authentication data. High-impact banking actions should require human approval and existing transaction controls.

## API and service boundaries

- Request bodies are size-limited before parsing, metadata filters use an allowlist, and Pydantic validates all external models.
- Exact CORS origins and trusted hosts are configured from the environment. Security headers disable framing, MIME sniffing, caching, sensitive browser capabilities, and broad content loading.
- Production mode redirects HTTP to HTTPS and disables interactive API documentation.
- The enterprise data service is internal-only in Docker Compose and requires a timing-safe shared-secret check. The secret is sent in a header, never a URL.
- Every protected API is subject to the per-user token bucket. Request IDs are attached to logs and responses for audit correlation.
- Containers run as an unprivileged user with a read-only root filesystem, a temporary `/tmp`, and `no-new-privileges`.

## Authentication caveat

Assignment Option A local accounts use salted PBKDF2-HMAC-SHA256 with 600,000 iterations and timing-safe comparison. Production refuses to start with demo passwords or placeholder MCP secrets. Production should still replace Basic authentication with OIDC/Keycloak, short-lived tokens, centralized revocation, a secret manager, audit retention, and key rotation.

## Residual risk

No software can truthfully claim absolute security. This POC does not include a managed WAF, enterprise DLP/classifier, SIEM, mTLS service identity, vulnerability-scanned immutable images, key rotation, or external penetration testing. Those controls remain deployment responsibilities and are required before handling real bank or customer data.

## Verification

Run `ruff check .`, `pytest -q`, `bandit -r app ui scripts -q`, and `pip-audit` before release. At the time of submission all tests and static checks pass and the dependency audit reports no known vulnerabilities.
