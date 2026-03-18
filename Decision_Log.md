# Decision Log — Monday.com BI Agent

**Max 2 pages.** Key technical and product decisions, rationale, and trade-offs.

---

## 1. Tech stack

| Choice | Rationale |
|--------|-----------|
| **Python 3.10+** | Fast to build, strong ecosystem for APIs and agents. |
| **Streamlit** | Single-file UI, minimal setup, good for a hosted prototype evaluators can open without install. |
| **Microsoft Agent Framework + Azure OpenAI** | Native tool-calling and session support; fits “agent that calls tools” model. Azure OpenAI for enterprise-friendly deployment and compliance. |
| **Monday.com GraphQL API (v2)** | Official API, supports filtering, pagination, and schema introspection. No MCP used; tool-calling is via the framework’s function tools. |
| **Config: `config.yaml` + `.env`** | Board IDs in YAML (versionable, no code change to add boards); secrets in `.env` (no tokens in repo). |

---

## 2. Live query-time fetching (no preload / cache)

- **Decision:** Every user question triggers **live** Monday.com API calls. No preloading of boards or items and no cache layer.
- **How:** The agent decides which tools to call per query. Each tool (`get_schema`, `get_unique_values`, `get_items_filtered`, `get_items_page`, etc.) calls `run_graphql()` and sends an HTTP POST to `https://api.monday.com/v2`. Data is used only for that turn.
- **Flow:** User query → Agent interprets and selects tools → Each tool runs → `run_graphql()` → Monday API → Response returned to agent → Agent may call more tools (e.g. paginate) → Agent synthesizes answer.
- **Trade-off:** Slightly higher latency per query vs. requirement for “live at query time”; we prioritized correctness and simplicity over caching.

---

## 3. Data resilience and messy data

- **Missing / null:** Column values are normalized in tools via `_text_from_column_value()`; missing or empty values become `None` or empty string in the normalized item dict. The system prompt instructs the agent to mention data quality caveats when relevant.
- **Inconsistent formats:** `get_unique_values(board_id, column_id)` is used so the agent can **discover** exact values (e.g. “Pharma”, “Hospitals”) before filtering, instead of assuming user wording (“healthcare”) matches the board. This maps user language to actual column values.
- **Filter fallback:** If `get_items_filtered` returns no items, the prompt tells the agent to use `get_items_page` and reason over a raw page so it can still answer (e.g. when column type doesn’t support API filtering).

---

## 4. Query understanding and BI behaviour

- **Board/schema in prompt:** At **prompt build time** (server start / first use), we call `get_boards()` and `get_schema(board_ids)` once to inject board names, IDs, and column metadata (id, title, type, allowed_values) into the system prompt. This is **not** a data cache: it only tells the agent which boards and columns exist. All **row-level** data is still fetched at query time via tools.
- **ReAct-style workflow:** The prompt defines a clear SOP: choose board(s) from context → identify column IDs → call `get_unique_values` for categorical filters → call `get_items_filtered` (or `get_items_filtered_by_value_any_column`) with exact values → paginate with `cursor` → synthesize and mention anomalies.
- **Cross-board:** Both boards (e.g. Deals, Work Orders) are in config and schema; the agent can call tools on different `board_id`s in one conversation when the question spans pipeline and work orders.
- **Clarifications:** The prompt instructs the agent to ask one short clarifying question when the request is ambiguous.

---

## 5. Agent action visibility (tool-call trace)

- **Decision:** Use **function middleware** to record every tool invocation and surface it in the UI.
- **Implementation:** `tracing_middleware.trace_tool_calls` runs around each tool call; it appends to a `trace_collector` list (passed via `agent.run(trace_collector=...)`) with tool name, arguments summary, duration (ms), and status (ok/error). The Streamlit app passes `trace_collector` per request and shows “Traces & observability” in the sidebar with expandable entries and total tool time.
- **Result:** Evaluators see exactly which Monday.com tools were called, with what arguments, and how long they took, satisfying “visible API/tool-call trace.”

---

## 6. Error handling and security

- **Exceptions:** `monday_tools` defines `MondayAPIError` (API/auth/HTTP/GraphQL), `ConfigError` (missing/invalid config), `ValidationError` (bad tool args). These are raised and logged; the agent sees failures and can retry or explain.
- **Guardrails in prompt:** The agent is told not to expose internal details (board IDs, column IDs, tool names) to the user—only board **names** and column **titles**. It is also instructed to refuse off-topic or out-of-scope questions politely.

---

## 7. Summary

| Requirement | Approach |
|-------------|----------|
| Live Monday.com integration | GraphQL API v2, tool-calling only; every query triggers API calls. |
| No preload/cache | No in-memory or file cache; schema injection is metadata-only at prompt build. |
| Data resilience | Normalized column values, `get_unique_values` for mapping, fallback to `get_items_page`. |
| Query understanding | Injected boards/schema + ReAct SOP + optional clarifying question. |
| BI across boards | Multi-board config; agent calls tools on the relevant board_id(s). |
| Visible tool trace | Middleware + trace_collector + Streamlit sidebar. |

---

*End of Decision Log.*
