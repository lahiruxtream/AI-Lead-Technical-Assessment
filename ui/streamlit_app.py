"""Streamlit chat client with conversation history and transparent agent activity."""

import json
import os
import uuid

import httpx
import streamlit as st

st.set_page_config(page_title="Commercial Bank Knowledge AI", page_icon="🏦", layout="wide")
st.title("🏦 Commercial Bank Knowledge Assistant")
st.caption("Grounded enterprise answers with transparent agent activity")

api_url = os.getenv("API_URL", "http://localhost:8000")
role_descriptions = {
    "viewer": "Search and chat",
    "analyst": "Search, analytics, and MCP tools",
    "admin": "All tools and confidential evidence",
}

# Render a real credential form before creating or displaying any conversation state.
if not st.session_state.get("authenticated"):
    login_left, login_center, login_right = st.columns([1, 1.3, 1])
    with login_center:
        st.subheader("Sign in")
        st.caption("Use your enterprise demo account to continue.")
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="viewer, analyst, or admin")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            try:
                # A protected endpoint verifies credentials; the UI never decides the user's role.
                response = httpx.get(
                    f"{api_url}/v1/conversations",
                    auth=(username.strip(), password),
                    timeout=5,
                )
                response.raise_for_status()
                if username.strip() not in role_descriptions:
                    raise ValueError("Unsupported demo account")
                st.session_state.authenticated = True
                st.session_state.auth_username = username.strip()
                st.session_state.auth_password = password
                st.session_state.messages = []
                st.session_state.session_id = str(uuid.uuid4())
                st.rerun()
            except (httpx.HTTPError, ValueError):
                st.error("Invalid username or password, or the API is unavailable.")
        with st.expander("Demo credentials"):
            st.code("viewer / viewer123\nanalyst / analyst123\nadmin / admin123")
    st.stop()

# These values exist only after the backend has accepted the credentials.
role = st.session_state.auth_username
auth = (role, st.session_state.auth_password)

if "messages" not in st.session_state:
    # Streamlit reruns this module on interaction, so durable UI state lives in session_state.
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

with st.sidebar:
    st.header("Signed in")
    st.write(f"**{role}**")
    st.info(role_descriptions[role])
    if st.button("Sign out", use_container_width=True):
        # Remove credentials and user-specific UI state before returning to the login page.
        for key in (
            "authenticated",
            "auth_username",
            "auth_password",
            "messages",
            "session_id",
        ):
            st.session_state.pop(key, None)
        st.rerun()
    department = st.selectbox("Department filter", ["All", "payments", "platform", "security"])
    if st.button("New conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.rerun()

    st.divider()
    st.subheader("Conversation history")
    try:
        history_response = httpx.get(
            f"{api_url}/v1/conversations", auth=auth, timeout=5
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
                    auth=auth, timeout=5,
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
                    auth=auth,
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
    # The UI consumes named SSE events so operational activity and answer tokens stay separate.
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
                auth=auth,
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
