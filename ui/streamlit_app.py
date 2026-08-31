import json
import os
import uuid

import httpx
import streamlit as st

st.set_page_config(page_title="Commercial Bank Knowledge AI", page_icon="🏦", layout="wide")
st.title("🏦 Commercial Bank Knowledge Assistant")
st.caption("Grounded enterprise answers with transparent agent activity")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

api_url = os.getenv("API_URL", "http://localhost:8000")
passwords = {
    "viewer": os.getenv("VIEWER_PASSWORD", "viewer123"),
    "analyst": os.getenv("ANALYST_PASSWORD", "analyst123"),
    "admin": os.getenv("ADMIN_PASSWORD", "admin123"),
}

with st.sidebar:
    st.header("Demo access")
    role = st.selectbox("Role", ["viewer", "analyst", "admin"])
    if st.session_state.get("loaded_role") != role:
        st.session_state.loaded_role = role
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
    st.info({
        "viewer": "Search and chat",
        "analyst": "Search, analytics, MCP",
        "admin": "All tools",
    }[role])
    department = st.selectbox("Department filter", ["All", "payments", "platform", "security"])
    if st.button("New conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()

    st.divider()
    st.subheader("Conversation history")
    try:
        history_response = httpx.get(
            f"{api_url}/v1/conversations", auth=(role, passwords[role]), timeout=5
        )
        history_response.raise_for_status()
        conversations = history_response.json()
        if conversations:
            labels = {
                item["session_id"]: f"{item['title']} · {item['updated_at'][:10]}"
                for item in conversations
            }
            selected = st.selectbox(
                "Saved chats",
                options=[item["session_id"] for item in conversations],
                format_func=lambda session: labels[session],
                index=None,
                placeholder="Select a previous chat",
            )
            if selected and selected != st.session_state.session_id:
                saved = httpx.get(
                    f"{api_url}/v1/conversations/{selected}",
                    auth=(role, passwords[role]), timeout=5,
                )
                saved.raise_for_status()
                st.session_state.session_id = selected
                st.session_state.messages = saved.json()["messages"]
                st.rerun()
        else:
            st.caption("No saved conversations yet.")
    except httpx.HTTPError:
        st.caption("History becomes available when the API is running.")

    st.divider()
    with st.form("quality_feedback"):
        st.subheader("Answer feedback")
        rating_label = st.radio("Latest answer", ["Helpful", "Needs improvement"], horizontal=True)
        feedback_comment = st.text_input("Comment (optional)", max_chars=1000)
        if st.form_submit_button("Send feedback", use_container_width=True):
            try:
                result = httpx.post(
                    f"{api_url}/v1/feedback",
                    json={
                        "session_id": st.session_state.session_id,
                        "rating": 1 if rating_label == "Helpful" else -1,
                        "comment": feedback_comment,
                    },
                    auth=(role, passwords[role]),
                    timeout=5,
                )
                result.raise_for_status()
                st.success("Feedback recorded")
            except httpx.HTTPError:
                st.error("Send a chat message before submitting feedback.")

chat_col, activity_col = st.columns([3, 2])
with chat_col:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("citations"):
                with st.expander("Supporting evidence"):
                    for citation in message["citations"]:
                        st.markdown(f"**[{citation['document_id']}] {citation['title']}** — score `{citation['score']}`")
                        st.caption(citation["text"][:500])

prompt = st.chat_input("Ask about policies, architecture, runbooks, incidents, or products…")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with chat_col, st.chat_message("user"):
        st.markdown(prompt)
    activity_box = activity_col.container(border=True)
    activity_box.subheader("Live agent activity")
    status = activity_box.status("Agent started", expanded=True)
    answer_placeholder = chat_col.empty()
    answer = ""
    citations = []
    payload = {
        "message": prompt,
        "session_id": st.session_state.session_id,
        "filters": {} if department == "All" else {"department": department},
    }
    try:
        with (
            httpx.Client(timeout=60) as client,
            client.stream(
                "POST", f"{api_url}/v1/chat/stream", json=payload,
                auth=(role, passwords[role]),
            ) as response,
        ):
                response.raise_for_status()
                event_name = "message"
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event_name = line.removeprefix("event:").strip()
                    elif line.startswith("data:"):
                        event = json.loads(line.removeprefix("data:").strip())
                        if event_name == "token":
                            answer += event["message"]
                            answer_placeholder.chat_message("assistant").markdown(answer + "▌")
                        elif event_name == "final":
                            answer = event["message"]
                            citations = event["data"].get("citations", [])
                        elif event_name == "error":
                            raise RuntimeError(event["message"])
                        else:
                            icon = {"state": "🔄", "tool": "🛠️", "retrieval": "🔎", "memory": "🧠", "validation": "🛡️"}.get(event_name, "•")
                            status.write(f"{icon} **{event['node']}** — {event['message']}")
        status.update(label="Agent completed", state="complete", expanded=True)
        answer_placeholder.chat_message("assistant").markdown(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer, "citations": citations})
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        status.update(label="Request failed", state="error")
        answer_placeholder.error(f"Assistant unavailable: {exc}")
