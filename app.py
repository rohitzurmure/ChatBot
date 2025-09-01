import streamlit as st
import google.generativeai as genai


# --- 0. Configure API Key securely ---
# Use st.secrets to access the API key from .streamlit/secrets.toml
try:
    # Ensure your actual API key is in .streamlit/secrets.toml
    # e.g., GOOGLE_API_KEY="YOUR_GEMINI_API_KEY"
    genai.configure(api_key="")
except KeyError:
    st.error("Gemini API Key not found. Please set it in .streamlit/secrets.toml as GOOGLE_API_KEY.")
    st.stop() # Stop the app if key is missing

# --- 1. Configure Streamlit UI ---
st.set_page_config(page_title="Gemini Chatbot", page_icon="🤖")
st.title("💬 Gemini Chatbot")

# --- 2. Sidebar for Model Parameters ---
with st.sidebar:
    st.header("Model Settings")

    # Sliders for temperature and max_output_tokens
    # These values will be used to configure the chat session dynamically
    temperature = st.slider(
        "Temperature",
        min_value=0.0,
        max_value=1.0,
        value=0.7, # Default value
        step=0.05,
        help="Controls the randomness of the output. Lower values (closer to 0) make responses more deterministic. Higher values (closer to 1) make responses more creative and varied."
    )

    max_output_tokens = st.slider(
        "Max Output Tokens",
        min_value=50,
        max_value=65000, # Adjust max based on model's actual max (e.g., gemini-pro can be higher)
        value=65000, # Default value
        step=50,
        help="The maximum number of tokens to generate in the response. Useful for controlling response length and cost."
    )

    
    
    
# --- 3. Load the Gemini model (cached for performance) ---
@st.cache_resource
def load_gemini_model():
    """Loads the GenerativeModel once and caches it."""
    try:
        # Load the base model without generation_config here.
        # generation_config will be applied when starting a chat session.
        return genai.GenerativeModel("gemini-2.5-flash") # Or "gemini-1.5-flash", "gemini-pro"
    except Exception as e:
        st.error(f"Error loading Gemini model: {e}")
        st.stop() # Stop execution if model can't be loaded

model = load_gemini_model()

# --- 4. Initialize chat history and chat session ---
# Initialize messages list in session state if not already present
if "messages" not in st.session_state:
    st.session_state.messages = []

# Store the current model parameters in session state
# This allows us to detect if the sliders have changed
if "last_temperature" not in st.session_state:
    st.session_state.last_temperature = temperature
if "last_max_output_tokens" not in st.session_state:
    st.session_state.last_max_output_tokens = max_output_tokens


# Check if model parameters have changed or if chat_session needs initial setup
if (st.session_state.last_temperature != temperature or
    st.session_state.last_max_output_tokens != max_output_tokens or
    "chat_session" not in st.session_state): # True on first run or after clearing session

    st.session_state.messages = [] # Clear history because parameters changed

    # Define generation and safety settings based on current slider/selectbox values
    current_generation_config = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }

    
    # Start a new chat session with the updated parameters
    st.session_state.chat_session = model.start_chat(
        history=[]
        
        
    )

    # Update the stored last parameters
    st.session_state.last_temperature = temperature
    st.session_state.last_max_output_tokens = max_output_tokens
   
    # If parameters changed and caused a re-init, rerun to clear displayed chat
    # Only rerun if it's not the very first load
    if st.session_state.messages: # Check if messages were already present before clearing
        st.rerun()


# --- 5. Display chat history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- 6. User input and AI response generation ---
if user_input := st.chat_input("Type your message..."):
    # Append user message to chat history
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Display a placeholder for the assistant's response (for streaming)
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        try:
            # Send message to the *persisted* chat session and stream the response
            # The generation_config and safety_settings are already set on chat_session
            for chunk in st.session_state.chat_session.send_message(user_input, stream=True):
                full_response += chunk.text
                # Update the placeholder with the streamed content and a blinking cursor
                message_placeholder.markdown(full_response + "▌")
            # Final display without the blinking cursor
            message_placeholder.markdown(full_response)
        except Exception as e:
            full_response = f"Error: {e}"
            st.error(full_response)

        # Append assistant's full response to chat history
        st.session_state.messages.append({"role": "assistant", "content": full_response})

# --- 7. Clear chat button ---
if st.button("Clear Chat"):
    st.session_state.messages = []  # Clear message history
    # Reset chat session to ensure it picks up current slider values
    # By deleting chat_session, the next run will trigger the re-initialization logic above
    del st.session_state["chat_session"] 
    st.rerun() # Rerun the app to clear the displayed chat and re-initialize session