"""
Streamlit UI: chat (user + agent only) and sidebar with traces/observability.
"""
import logger  # noqa: F401 — configure logging to logs/app.log before other imports
import asyncio
import streamlit as st

from agent_run import get_ai_response
from AgentService import agent_service


def ensure_agent_initialized():
    if not getattr(st.session_state, "agent_initialized", False):
        try:
            asyncio.run(agent_service.initialize())
            st.session_state.agent_initialized = True
        except Exception as e:
            st.error(f"Failed to initialize agent: {e}")
            raise


def init_session_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "last_traces" not in st.session_state:
        st.session_state.last_traces = []


def main():
    st.set_page_config(page_title="Monday BI Agent", layout="wide")
    init_session_state()
    ensure_agent_initialized()

    # ---- Sidebar: traces and observability ----
    with st.sidebar:
        if st.button("New conversation"):
            st.session_state.messages = []
            st.session_state.session_id = None
            st.session_state.last_traces = []
            st.rerun()
        st.header("Traces & observability")
        st.caption("Tool calls and timing for the latest response")
        if st.session_state.last_traces:
            for i, t in enumerate(st.session_state.last_traces):
                status = t.get("status", "ok")
                tool_name = t.get("tool", "?")
                duration_ms = t.get("duration_ms", 0)
                with st.expander(f"**{tool_name}** — {duration_ms:.1f} ms — {status}", expanded=True):
                    st.json({
                        "tool": tool_name,
                        "duration_ms": duration_ms,
                        "status": status,
                        "arguments": t.get("arguments", ""),
                        **({"error": t.get("error")} if t.get("error") else {}),
                    })
            total_ms = sum(t.get("duration_ms", 0) for t in st.session_state.last_traces)
            st.metric("Total tool time", f"{total_ms:.1f} ms")
        else:
            st.info("Send a message to see tool call traces here.")

    # ---- Main: chat (user + agent only) ----
    st.title("Monday BI Agent")
    st.caption("Chat with the agent. Only your messages and the agent’s replies are shown here.")

    for msg in st.session_state.messages:
        role = msg["role"]
        content = msg["content"]
        with st.chat_message(role):
            st.markdown(content)

    if prompt := st.chat_input("Ask something..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        trace_collector = []
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response, new_session_id = get_ai_response(
                        prompt,
                        session_id=st.session_state.session_id,
                        trace_collector=trace_collector,
                    )
                    st.session_state.session_id = new_session_id
                    st.session_state.last_traces = trace_collector
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                except Exception as e:
                    st.error(str(e))
                    st.session_state.last_traces = []

        # Rerun so sidebar shows the new traces right away (no need to send another message)
        st.rerun()


if __name__ == "__main__":
    main()
