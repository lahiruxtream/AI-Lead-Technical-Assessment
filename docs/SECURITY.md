# Security model

## Trust boundaries

- User input, retrieved documents, and MCP responses are untrusted.
- Role authorization is enforced inside every tool, not delegated to the LLM or routing prompt.
- Retrieval filters evidence by access level before text reaches the model.
- The analytics tool exposes predefined operations; it does not execute model-generated Python or use `eval`.

## Prompt injection and exfiltration

Requests matching instruction override, prompt disclosure, secret extraction, or RBAC bypass patterns are rejected. The system prompt says evidence is data, not instruction. This layered approach reduces common attacks but pattern matching alone is not a complete production defense; add a dedicated classifier, DLP, output policy model, and red-team evaluation.

## Grounding and citations

The model is told to answer only from retrieved evidence and use `[document-id]` citations. A deterministic post-validator compares every citation to authorized retrieved IDs and strips invalid citations. Insufficient evidence produces an explicit non-answer.

## Brand safety

The assistant identifies as a Commercial Bank internal assistant, avoids unsupported financial claims, never advises disabling fraud controls, and does not expose credentials or customer authentication data. High-impact banking actions should require human approval and existing transaction controls.

## Authentication caveat

Hardcoded SHA-256 password hashes demonstrate the assignment's Option A only. SHA-256 is not suitable for real password storage. Production must use OIDC/Keycloak, TLS, short-lived tokens, Argon2/bcrypt where passwords remain, secret management, audit trails, and key rotation.
