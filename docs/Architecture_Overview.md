# Brief Architecture Overview — Monday.com BI Agent

This document describes the architecture of the Monday.com Business Intelligence Agent: high-level components, data flow, and query lifecycle. Diagrams use [Mermaid](https://mermaid.js.org/) and render in GitHub, VS Code (with a Mermaid extension), and many Markdown viewers.

---

## 1. High-Level Architecture

The system is a conversational BI agent: the user asks questions in natural language; the agent calls Monday.com via tools and uses an LLM to synthesize answers. All data is fetched at query time (no preload or cache).

```mermaid
flowchart TB
    subgraph User["User"]
        U[User]
    end

    subgraph App["Application (Python)"]
        UI[Streamlit UI]
        AR[agent_run]
        SV[AgentService]
        AG[Agent Framework + LLM]
        MW[tracing_middleware]
        T[Monday Tools]
    end

    subgraph Config["Configuration"]
        CFG[config.yaml]
        ENV[.env]
    end

    subgraph External["External Services"]
        AZ[Azure OpenAI]
        MON[Monday.com GraphQL API]
    end

    U <-->|"Chat"| UI
    UI --> AR
    AR --> SV
    SV --> AG
    AG -->|"Tool calls"| T
    AG <-->|"Chat completions"| AZ
    T -->|"HTTP POST GraphQL"| MON
    SV --> CFG
    T --> CFG
    SV --> ENV
    T --> ENV
    MW -.->|"Wraps"| T
```

---

## 2. Component Diagram

```mermaid
flowchart LR
    subgraph Presentation["Presentation Layer"]
        A[app_streamlit.py]
    end

    subgraph Application["Application Layer"]
        B[agent_run.py]
        C[AgentService.py]
    end

    subgraph Agent["Agent & LLM"]
        D[Agent Framework]
        E[Azure OpenAI]
        F[prompts.py]
    end

    subgraph Tools["Tool Layer"]
        G[monday_tools.py]
        H[tracing_middleware.py]
    end

    subgraph Data["Data / Config"]
        I[config.yaml]
        J[.env]
        K[Monday.com API]
    end

    A --> B
    B --> C
    C --> D
    C --> F
    D --> E
    D --> G
    H -.-> G
    G --> K
    C --> I
    G --> I
    C --> J
    G --> J
```

| Layer | Components | Responsibility |
|-------|-------------|----------------|
| **Presentation** | `app_streamlit.py` | Chat UI, session state, trace sidebar. |
| **Application** | `agent_run.py`, `AgentService.py` | Session creation, run/stream agent, inject trace_collector. |
| **Agent** | Agent Framework, Azure OpenAI, `prompts.py` | System prompt (boards/schema), tool-calling, multi-turn chat. |
| **Tools** | `monday_tools.py`, `tracing_middleware.py` | Monday.com GraphQL calls, normalization, trace recording. |
| **Data** | `config.yaml`, `.env`, Monday.com | Board IDs, API token, live board data. |

---

## 3. End-to-End Query Flow (Sequence)

This sequence shows what happens when a user sends one message.

```mermaid
sequenceDiagram
    participant U as User
    participant ST as Streamlit
    participant AR as agent_run
    participant SV as AgentService
    participant AG as Agent
    participant T as Monday Tools
    participant API as Monday.com API
    participant AZ as Azure OpenAI

    U->>ST: Ask question (e.g. "Pipeline for energy?")
    ST->>AR: get_ai_response(query, session_id, trace_collector)
    AR->>SV: run(query, session_id, trace_collector)

    alt No session
        SV->>SV: create_session()
    end

    loop Agent ReAct loop (until final answer)
        SV->>AG: run(query, session, trace_collector)
        AG->>AZ: Chat completion (with tool_calls)
        AZ-->>AG: Tool names + args
        AG->>T: Invoke tool (e.g. get_items_filtered)
        T->>API: POST GraphQL
        API-->>T: JSON items/cursor
        T-->>AG: Normalized items
        AG->>AG: Append to trace_collector (middleware)
        AG->>AZ: Next completion (tool results)
        AZ-->>AG: Next tool_calls or final text
    end

    AG-->>SV: response.text
    SV-->>AR: (response, session_id)
    AR-->>ST: (response, session_id)
    ST->>ST: Update messages & last_traces
    ST->>U: Display answer + sidebar traces
```

---

## 4. Agent Tool-Call Flow (Detail)

The agent follows a ReAct-style workflow: reason about the query, call tools, then synthesize. This diagram shows the decision flow and tool usage.

```mermaid
flowchart TD
    A[User query] --> B[Agent receives query]
    B --> C{Need board/schema?}
    C -->|Yes| D[get_boards / get_schema]
    C -->|No| E[Use injected schema]
    D --> F[Identify board_id & column_ids]
    E --> F
    F --> G{Categorical filter?}
    G -->|Yes| H[get_unique_values]
    G -->|No| I[Proceed to fetch]
    H --> I
    I --> J[get_items_filtered or get_items_filtered_by_value_any_column]
    J --> K{More pages?}
    K -->|cursor not null| J
    K -->|Done| L[get_items_page fallback if filter empty]
    L --> M[Agent synthesizes answer]
    M --> N[Return to user]
```

---

## 5. Data Flow Overview

```mermaid
flowchart LR
    subgraph Inputs
        Q[User question]
        S[Session history]
        P[System prompt + boards/schema]
    end

    subgraph AgentCore["Agent core"]
        LLM[LLM]
        TC[Tool calls]
    end

    subgraph Monday["Monday.com"]
        GQL[GraphQL API]
        BOARDS[Boards: Deals, Work Orders]
    end

    subgraph Outputs
        ANS[Answer text]
        TR[Tool traces]
    end

    Q --> LLM
    S --> LLM
    P --> LLM
    LLM --> TC
    TC --> GQL
    GQL --> BOARDS
    GQL --> TC
    TC --> LLM
    LLM --> ANS
    TC --> TR
```

- **Inputs:** User question, session history, and system prompt (with board list and column schema injected at prompt build time).
- **Agent core:** LLM decides which tools to call; tools run and return data; LLM may call again (e.g. pagination) or produce the final answer.
- **Monday.com:** All row-level data is read via GraphQL at query time; no local cache.
- **Outputs:** Answer text to the user and tool-call traces (tool name, args, duration, status) shown in the sidebar.

---

## 6. Deployment / Stack View

```mermaid
flowchart TB
    subgraph Client["Client"]
        Browser[Browser]
    end

    subgraph Server["Server (e.g. single host)"]
        subgraph Process["Python process"]
            Streamlit[Streamlit]
            AgentService[AgentService]
            Tools[Monday tools]
        end
    end

    subgraph Cloud["Cloud services"]
        Azure[Azure OpenAI]
        Monday["Monday.com API"]
    end

    Browser <-->|HTTPS| Streamlit
    Streamlit --> AgentService
    AgentService --> Tools
    AgentService -->|HTTPS| Azure
    Tools -->|HTTPS| Monday
```

- **Client:** User accesses the app in a browser (e.g. Streamlit default port 8501).
- **Server:** One Python process runs Streamlit; it initializes AgentService once and reuses it; all Monday tools run in the same process.
- **Cloud:** Azure OpenAI for the model; Monday.com for live board data.

---

## 7. File Map (Logical View)

```mermaid
flowchart TD
    app_streamlit["app_streamlit.py\n(UI entry)"]
    agent_run["agent_run.py\n(get_ai_response)"]
    AgentService["AgentService.py\n(singleton agent)"]
    prompts["prompts.py\n(system prompt + schema)"]
    monday_tools["monday_tools.py\n(GraphQL tools)"]
    tracing["tracing_middleware.py\n(tool trace)"]
    config["config.yaml"]
    env[".env"]

    app_streamlit --> agent_run
    app_streamlit --> AgentService
    agent_run --> AgentService
    AgentService --> prompts
    AgentService --> monday_tools
    AgentService --> tracing
    prompts --> monday_tools
    monday_tools --> config
    monday_tools --> env
```

---

## 8. Summary

| Aspect | Description |
|--------|-------------|
| **Entry** | Streamlit app; user chats in the browser. |
| **Orchestration** | AgentService holds the Agent Framework agent; agent_run runs it per message and passes trace_collector. |
| **Reasoning** | Azure OpenAI LLM with a ReAct-style system prompt; board/column context injected at prompt build. |
| **Data access** | Monday.com GraphQL API only; tools (get_boards, get_schema, get_unique_values, get_items_filtered, get_items_page, etc.) run at query time with no cache. |
| **Observability** | Middleware records each tool call into trace_collector; Streamlit shows traces in the sidebar. |
| **Config** | config.yaml for board IDs; .env for MONDAY_API_TOKEN and Azure OpenAI settings. |

For implementation details, see the codebase and `Decision_Log.md` / `Decision_Log.txt`.
