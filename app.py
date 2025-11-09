import os
import time
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
import google.generativeai as genai

# Load environment variables from a local .env file (if present)
load_dotenv()

app = Flask(__name__)

# Read API key from environment. Prefer GENAI_API_KEY, fall back to common names.
API_KEY = os.environ.get("GENAI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("API_KEY")
if not API_KEY:
    raise RuntimeError(
        "GENAI API key not set. Please set GENAI_API_KEY in the environment or in a .env file."
    )

genai.configure(api_key=API_KEY)
print(f"GENAI configured. Using API key present: {'yes' if API_KEY else 'no'}")
MODEL_NAME = os.environ.get("GENAI_MODEL") or os.environ.get("MODEL") or "gemini-2.5-flash"
print(f"Using model: {MODEL_NAME}")

def chat_with_gemini(history, retries=3):
    # Model name is configured at module load (MODEL_NAME)
    model = genai.GenerativeModel(MODEL_NAME)
    # history: list of {role: 'user'|'bot', content: str}
    # Build a conversation string
    conversation = ''
    for msg in history:
        if msg.get('role') == 'user':
            conversation += f"You: {msg.get('content','')}\n"
        else:
            conversation += f"Bot: {msg.get('content','')}\n"

    # Exponential backoff retry loop. Raise on non-retryable errors (like 403 leaked key).
    backoff = 1
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            response = model.generate_content(conversation)
            return response.text.strip()
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            # Detect leaked/invalid API key errors and fail fast so client sees structured error
            if '403' in msg or 'leaked' in msg or 'invalid' in msg or 'permission' in msg:
                print(f"Non-retryable error from generative API: {e}")
                # Raise to allow the HTTP handler to return a JSON error payload
                raise RuntimeError(f"Generative API error: {e}")
            # Otherwise, retry with exponential backoff
            if attempt < retries:
                print(f"Transient error: {e}. Retrying in {backoff}s (attempt {attempt}/{retries})...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10)
            else:
                print(f"All retries exhausted. Last error: {e}")
                # Raise so the caller can return a structured JSON error
                raise RuntimeError(f"Generative API failed after {retries} attempts: {e}")
@app.route('/')
def serve_index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')
@app.route('/api/submit', methods=['POST'])
def handle_submit():
    data = request.get_json()
    history = data.get('history', [])
    try:
        print(f"Received /api/submit request. History length: {len(history)}")
        response_text = chat_with_gemini(history)
        # Ensure we always return JSON
        return jsonify({'response': response_text})
    except Exception as e:
        # Log server-side error and return JSON error payload
        print(f"Error in /api/submit: {e}")
        return jsonify({'error': 'Internal server error', 'detail': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    # If certs exist in the project root (cert.pem and key.pem), enable HTTPS
    base = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(base, 'cert.pem')
    key_path = os.path.join(base, 'key.pem')
    if os.path.exists(cert_path) and os.path.exists(key_path):
        print(f"Found certificate files; starting HTTPS on port {port}")
        app.run(host="0.0.0.0", port=port, ssl_context=(cert_path, key_path))
    else:
        print(f"Certificate files not found; starting HTTP on port {port}")
        app.run(host="0.0.0.0", port=port)
