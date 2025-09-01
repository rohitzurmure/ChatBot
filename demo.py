import streamlit as st
import google.generativeai as genai
import sqlite3
from datetime import datetime
import json

# --- Database Utilities ---
DB_NAME = "chat_history.db"

def init_db():
    """Initializes the SQLite database and creates tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

def save_chat_thread(chat_id, chat_name, messages):
    """Saves or updates a chat thread and its messages in the database."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if not chat_name:
        st.error("Chat name cannot be empty for saving.")
        return None

    if chat_id is None: # New chat
        c.execute("INSERT INTO chats (name) VALUES (?)", (chat_name,))
        new_chat_id = c.lastrowid
        st.session_state.current_chat_id = new_chat_id # Update session state with new ID
        st.toast(f"New chat '{chat_name}' saved!", icon="💾")
    else: # Update existing chat
        c.execute("UPDATE chats SET name = ? WHERE id = ?", (chat_name, chat_id))
        c.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,)) # Clear old messages
        new_chat_id = chat_id # Keep existing ID
        st.toast(f"Chat '{chat_name}' updated!", icon="🔄")

    # Insert current messages
    for msg in messages:
        c.execute("INSERT INTO messages (chat_id, role, content) VALUES (?, ?, ?)",
                  (new_chat_id, msg["role"], msg["content"]))
    conn.commit()
    conn.close()
    return new_chat_id

def load_chat_thread(chat_id):
    """Loads messages for a given chat ID from the database."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT name FROM chats WHERE id = ?", (chat_id,))
    chat_name = c.fetchone()[0]

    c.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp", (chat_id,))
    messages = [{"role": row[0], "content": row[1]} for row in c.fetchall()]
    conn.close()
    return chat_name, messages

def get_all_chat_threads():
    """Retrieves all chat threads (ID and name) from the database."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT id, name, created_at FROM chats ORDER BY created_at DESC")
    threads = c.fetchall()
    conn.close()
    return threads

def delete_chat_thread(chat_id):
    """Deletes a chat thread and its messages from the database."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
    # ON DELETE CASCADE on messages table will handle deleting associated messages
    conn.commit()
    conn.close()
    st.toast(f"Chat deleted!", icon="🗑️")

# --- Helper function to convert st.session_state.messages to Gemini history format ---
def convert_to_gemini_history(messages):
    """Converts a list of dict messages to Gemini's expected history format."""
    gemini_history = []
    for msg in messages:
        # Gemini API expects 'user' and 'model' roles
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [msg["content"]]})
    return gemini_history

# --- 0. Configure API Key securely ---
try:
    # IMPORTANT: In a real app, use st.secrets["GOOGLE_API_KEY"]
    # For this example, I'm keeping the hardcoded key as it was, but this is INSECURE for production.
    genai.configure(api_key="")
except Exception as e:
    st.error(f"Gemini API Key configuration failed: {e}. Please ensure it's set correctly.")
    st.stop()

# --- Initialize Database ---
init_db()

# --- 1. Configure Streamlit UI ---
st.set_page_config(page_title="Gemini Chatbot with History", page_icon="🤖", layout="wide")
st.title("💬 Gemini Chatbot")

# --- Initialize session state variables ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = None # None indicates a new, unsaved chat
if "chat_name_input" not in st.session_state:
    st.session_state.chat_name_input = "" # For naming new chats or displaying current chat name
if "chat_session" not in st.session_state:
    st.session_state.chat_session = None # Gemini chat session object
if "last_temperature" not in st.session_state:
    st.session_state.last_temperature = None
if "last_max_output_tokens" not in st.session_state:
    st.session_state.last_max_output_tokens = None
if "loading_chat" not in st.session_state:
    st.session_state.loading_chat = False # Flag to prevent re-triggering logic when loading
if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = False # Flag for delete confirmation

# --- Sidebar for Model Parameters and Chat Management ---
with st.sidebar:
    st.header("Model Settings")

    temperature = st.slider(
        "Temperature",
        min_value=0.0, max_value=1.0, value=0.7, step=0.05,
        help="Controls the randomness of the output."
    )
    max_output_tokens = st.slider(
        "Max Output Tokens",
        min_value=50, max_value=65000, value=65000, step=50,
        help="The maximum number of tokens to generate."
    )

    st.header("Chat Management")

    current_chat_name = st.text_input(
        "Current Chat Name",
        value=st.session_state.chat_name_input,
        key="sidebar_chat_name_input",
        placeholder="Enter name for new chat"
    )
    # Update session state input if sidebar input changes
    if current_chat_name != st.session_state.chat_name_input:
        st.session_state.chat_name_input = current_chat_name
        # If the user is renaming an existing chat, save it immediately
        if st.session_state.current_chat_id is not None and st.session_state.messages:
             save_chat_thread(st.session_state.current_chat_id,
                              st.session_state.chat_name_input,
                              st.session_state.messages)
             st.rerun() # Rerun to update the history list immediately

    col1, col2 = st.columns(2)
    with col1:
        if st.button("➕ New Chat", use_container_width=True):
            if st.session_state.messages and not st.session_state.current_chat_id: # Has messages but is a new, unsaved chat
                if not st.session_state.chat_name_input:
                    st.warning("Please name the current chat before starting a new one, or click 'Clear Chat' if you don't want to save it.")
                    st.stop() # Prevent further execution until named or cleared
                else:
                    save_chat_thread(st.session_state.current_chat_id, # This will be None, saving as new
                                     st.session_state.chat_name_input,
                                     st.session_state.messages)
            elif st.session_state.messages and st.session_state.current_chat_id: # Existing chat with changes
                 save_chat_thread(st.session_state.current_chat_id,
                                  st.session_state.chat_name_input,
                                  st.session_state.messages)

            # Always clear and start fresh
            st.session_state.messages = []
            st.session_state.current_chat_id = None
            st.session_state.chat_name_input = ""
            st.session_state.chat_session = None # Forces re-initialization
            st.session_state.confirm_delete = False # Reset delete confirmation
            st.rerun()

    with col2:
        if st.button("💾 Save Chat", use_container_width=True, help="Save current chat to database"):
            if not st.session_state.messages:
                st.info("No messages to save in the current chat.")
            elif not st.session_state.chat_name_input:
                st.warning("Please enter a name for the chat before saving.")
            else:
                save_chat_thread(st.session_state.current_chat_id,
                                 st.session_state.chat_name_input,
                                 st.session_state.messages)
                # No need to rerun, just a confirmation message which is now a toast

    if st.session_state.current_chat_id: # Only show delete button if a chat is loaded/saved
        if st.button("🗑️ Delete Current Chat", use_container_width=True, key="delete_current_chat_btn"):
            st.session_state.confirm_delete = True # Set flag to show confirmation
            st.rerun() # Rerun to display confirmation buttons

        if st.session_state.confirm_delete:
            st.warning("Are you sure you want to delete this chat? This cannot be undone.", icon="⚠️")
            col_confirm_del1, col_confirm_del2 = st.columns(2)
            with col_confirm_del1:
                if st.button("✅ Confirm Delete", key="confirm_delete_yes", use_container_width=True):
                    delete_chat_thread(st.session_state.current_chat_id)
                    st.session_state.messages = []
                    st.session_state.current_chat_id = None
                    st.session_state.chat_name_input = ""
                    st.session_state.chat_session = None
                    st.session_state.confirm_delete = False # Reset flag
                    st.rerun()
            with col_confirm_del2:
                if st.button("❌ Cancel", key="confirm_delete_no", use_container_width=True):
                    st.session_state.confirm_delete = False # Reset flag
                    st.rerun()


    st.subheader("Your Chat History")
    chat_threads = get_all_chat_threads()
    if chat_threads:
        selected_chat_id = None
        for chat_thread_id, chat_thread_name, created_at in chat_threads:
            # Display each chat with a button to load it
            if st.button(f"📄 {chat_thread_name} ({created_at.split(' ')[0]})", key=f"load_chat_{chat_thread_id}", use_container_width=True):
                selected_chat_id = chat_thread_id

        if selected_chat_id and selected_chat_id != st.session_state.current_chat_id:
            # If a new chat is selected and it's different from the current one
            if st.session_state.messages and not st.session_state.current_chat_id: # Current is new, has messages
                 if not st.session_state.chat_name_input:
                     st.warning("You have unsaved messages in the current chat. Please name it and save, or start a new chat (which will discard this one) before loading another.")
                     st.stop() # Prevent loading until action is taken
                 else: # New chat has a name, auto-save it before loading
                     save_chat_thread(st.session_state.current_chat_id,
                                      st.session_state.chat_name_input,
                                      st.session_state.messages)

            # Proceed with loading the selected chat
            st.session_state.loading_chat = True # Set flag to prevent re-reinitialization during load
            loaded_name, loaded_messages = load_chat_thread(selected_chat_id)
            st.session_state.messages = loaded_messages
            st.session_state.current_chat_id = selected_chat_id
            st.session_state.chat_name_input = loaded_name
            st.session_state.chat_session = None # Force re-initialization with loaded history
            st.toast(f"Loaded chat: {loaded_name}", icon="📂")
            st.session_state.loading_chat = False
            st.session_state.confirm_delete = False # Reset delete confirmation
            st.rerun()
    else:
        st.info("No saved chats yet.")

# --- 3. Load the Gemini model (cached for performance) ---
@st.cache_resource
def load_gemini_model():
    """Loads the GenerativeModel once and caches it."""
    try:
        return genai.GenerativeModel("gemini-2.5-flash") # Or "gemini-1.5-flash", "gemini-pro"
    except Exception as e:
        st.error(f"Error loading Gemini model: {e}")
        st.stop()

model = load_gemini_model()

# --- 4. Initialize or re-initialize chat session based on parameters/history ---
# Check if model parameters have changed or if chat_session needs initial setup
# Also re-initialize if a chat was loaded from history
if (st.session_state.last_temperature != temperature or
    st.session_state.last_max_output_tokens != max_output_tokens or
    st.session_state.chat_session is None): # chat_session is None implies new/reloaded chat

    # Only clear messages if parameters truly changed, and not when loading a chat
    if (st.session_state.last_temperature is not None and
        st.session_state.last_max_output_tokens is not None and
        (st.session_state.last_temperature != temperature or
         st.session_state.last_max_output_tokens != max_output_tokens) and
        not st.session_state.loading_chat): # Don't clear if currently loading a chat
        st.session_state.messages = [] # Clear history if parameters changed

    # Convert current messages to Gemini history format
    initial_history = convert_to_gemini_history(st.session_state.messages)

    # Start a new chat session with the updated parameters and potentially loaded history
    st.session_state.chat_session = model.start_chat(
        history=initial_history,
        # safety_settings={...} can be added here if needed to apply to the whole session
    )

    # Update the stored last parameters
    st.session_state.last_temperature = temperature
    st.session_state.last_max_output_tokens = max_output_tokens
    # No need to rerun here, as the display logic will pick up new messages

# --- 5. Display chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 6. User input and AI response generation ---
# Disable input if a chat is loading or if delete confirmation is pending
input_disabled = st.session_state.loading_chat or st.session_state.confirm_delete

if user_input := st.chat_input("Type your message...", disabled=input_disabled):
    # Append user message to chat history
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Define generation config for this specific message
    current_generation_config = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }

    # Display a placeholder for the assistant's response (for streaming)
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        try:
            # Send message to the *persisted* chat session and stream the response
            # Pass generation_config and safety_settings here!
            for chunk in st.session_state.chat_session.send_message(
                user_input,
                stream=True,
                generation_config=current_generation_config,
                # safety_settings={...} can be added here if needed for this specific message
            ):
                full_response += chunk.text
                message_placeholder.markdown(full_response + "▌")
            message_placeholder.markdown(full_response)
        except Exception as e:
            full_response = f"Error: {e}"
            st.error(full_response)

        # Append assistant's full response to chat history
        st.session_state.messages.append({"role": "assistant", "content": full_response})

        # Auto-save/update current chat after a new message exchange
        if st.session_state.chat_name_input: # Only auto-save if a name is provided
            save_chat_thread(st.session_state.current_chat_id,
                             st.session_state.chat_name_input,
                             st.session_state.messages)
        elif not st.session_state.chat_name_input and st.session_state.messages:
            st.info("💡 Enter a chat name in the sidebar to automatically save your conversation progress!")