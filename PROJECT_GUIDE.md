# PyLab AI - Project Architecture & Technical Guide 🎓

This guide is designed to help you explain the technical details and architecture of **PyLab AI** to recruiters and technical interviewers.

---

## 1. Directory Structure Overview

Here is a breakdown of the repository and what each folder/file does:

*   **`app.py`**: The core of the Flask application. It defines all the API endpoints (routes), handles login sessions, manages database sync logic, and triggers background telemetry threads.
*   **`tracer_runner.py`**: The execution engine (sandbox) for running user Python code safely. It records stack frames, variable mutations, and outputs at each line.
*   **`google_apps_script.js`**: Webhook script deployed as a Google Web App. It receives data from Flask and dynamically appends rows to separate styled tabs (**Activity Logs**, **Code Runs**, etc.) inside your Google Sheet.
*   **`render.yaml`**: Deployment blueprint. Instructs Render on how to build (`pip install`) and run (`gunicorn`) the web app, and lists the environment variables needed.
*   **`database.db`**: Local SQLite database. Acts as a local fallback for offline development, storing user tables, user progress, streaks, and bookmarks.
*   **`templates/`**: HTML views rendered by Flask. Includes pages for learning, the code visualizer, profile dashboards, and AI mentor interfaces.
*   **`static/`**: Static frontend files including main stylesheet variables (`main.css`), visual themes, and client-side JavaScript (`main.js`).
*   **`content/` & `projects/`**: JSON configuration files storing educational lesson outlines, challenges, and step-by-step developer projects.

---

## 2. Deep-Dive: How the Code Visualizer Works (sys.settrace)

One of the most impressive technical features of PyLab AI is the step-by-step execution tracer. It visualizes exactly how Python executes code line-by-line.

### How it works behind the scenes:
1.  **Frontend Request**: The user enters a block of Python code in the visualizer UI and clicks "Run".
2.  **API Endpoint**: The visualizer sends a POST request with the code to the `/api/visualize-code` route in `app.py`.
3.  **Secure Subprocess**: To protect the main server, `app.py` writes the code to a temporary file and spawns a **separate python subprocess** running `tracer_runner.py` with a 5-second timeout (to block infinite loops).
4.  **Debugging Trace (`sys.settrace`)**: `tracer_runner.py` uses Python's native `sys.settrace()` API:
    *   It listens to `line`, `call`, and `return` events as the code runs.
    *   At each line, it serializes local variables, prints standard output (`stdout`), and tracks the current line number.
5.  **Data Serialization**: It packages this execution history into a structured JSON list of steps and returns it.
6.  **AI Line Explanations**: The Flask app sends the code to the **Gemini API**, which returns a friendly description of what each line does. This is mapped directly onto the steps and returned to the browser UI to display in real-time.

---

## 3. Deep-Dive: Dual-Pipeline Telemetry (Supabase + Google Sheets)

To track student progress and behavior, the application implements a dual-data pipeline:

```
                  ┌───────────────┐
                  │  Flask Route  │
                  └───────┬───────┘
                          │ (Asynchronous Thread)
                          ▼
            ┌─────────────┴─────────────┐
            ▼                           ▼
  ┌──────────────────┐        ┌──────────────────┐
  │ Supabase REST API│        │Google Webhook API│
  └────────┬─────────┘        └────────┬─────────┘
           ▼                           ▼
  ┌──────────────────┐        ┌──────────────────┐
  │ Secure DB Tables │        │Auto-Tabbed Sheets│
  └──────────────────┘        └──────────────────┘
```

### 1. Asynchronous Workers:
Logging can cause network latency. To prevent the site from feeling slow, all logging calls are wrapped in non-blocking python background threads (`threading.Thread`). They trigger instantly and complete in the background without making the user wait.

### 2. Supabase Integration:
Pushes logs to secure tables (`code_runs`, `user_sessions`, `ai_hint_usage`, `project_progress`). 
*   **Security**: Row-Level Security (RLS) is enabled on all tables in Supabase. The Flask backend uses a private `service_role` key from `.env` to safely bypass these RLS checks for server-to-database communication.

### 3. Google Sheets Integration:
Sends JSON payloads containing a `"table"` and `"data"` payload to your Apps Script Web App URL.
*   **Dynamic Routing**: The Apps Script checks the target `"table"` key and routes the log into its matching sheet tab (e.g. `Code Runs` or `Project Progress`).
*   **Dynamic Provisioning**: If a tab does not exist yet, the script calls `insertSheet()`, appends the headers, styles them with a slate background and cyan text, and resizes the columns automatically.

---

## 4. Key Security Features to Mention in Interviews

*   **Database Parameterization**: Prevent SQL Injection by using query parameters (`?` placeholders in SQLite and built-in URL filters in Supabase API) instead of raw string formatting.
*   **Password Hashing**: User passwords are safe and never stored as plain text. They are hashed using `pbkdf2:sha256` with randomized secure salts.
*   **Credential Isolation**: API keys and secrets are loaded dynamically from environment variables (`.env`) and never committed to GitHub.
*   **Execution Timeout**: Code sandbox executes user scripts inside a subprocess with a strict time limit (5 seconds) to prevent Denial of Service (DoS) attacks from infinite loops.
