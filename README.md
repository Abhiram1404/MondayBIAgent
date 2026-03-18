# Monday BI Agent

A chat application that lets you ask questions about your Monday.com boards in natural language. The app uses an AI agent that talks to Monday.com and Azure OpenAI to answer founder-level questions about pipeline, revenue, status, and more.

## Overview

- **Chat UI** — Streamlit-based interface to send questions and see answers.
- **Live data** — The agent uses the Monday.com API; no local copy of the data.
- **Boards** — Which boards are available is configured in `config.yaml`.

## How to start

### 1. Prerequisites

- Python 3.10+
- A Monday.com API token and Azure OpenAI credentials

### 2. Environment

Create a `.env` file in the project root and set:

- **Monday.com:** `MONDAY_API_TOKEN`
- **Azure OpenAI:** `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and your deployment name (e.g. `AZURE_OPENAI_DEPLOYMENT` or `AZURE_OPENAI_CHAT_DEPLOYMENT_NAME` depending on the code). Set `OPENAI_API_VERSION` if required.

Optional: `MONDAY_SSL_VERIFY`, `AZURE_OPENAI_SSL_VERIFY` (e.g. `false` for dev).

### 3. Config

Edit `config.yaml` so `Board_Ids` lists the Monday.com boards you want the agent to use (name and board ID).

### 4. Install and run

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

Open the URL shown in the terminal (usually http://localhost:8501) to use the chat.

### 5. New conversation

Use **New conversation** in the sidebar to clear the chat and start a fresh session.

---

For more detail on boards and columns, see `config.yaml` and the in-app system prompt behavior.
