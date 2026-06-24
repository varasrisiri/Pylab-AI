# PyLab AI 🚀

PyLab AI is an interactive, premium educational web application built to help developers learn, experiment with, and master Python. It features a line-by-line execution visualizer, real-time code execution tracing, AI-powered coding mentors, and dual-pipeline behavior analytics.

## 🌐 Live Application
The application is deployed and live at:
👉 **[https://pylab-ai.onrender.com](https://pylab-ai.onrender.com)**

---

## 🛠️ Key Features
* **Interactive Code Editor & Visualizer**: Run Python code and visualize call stack states, variable mutations, and logic flows step-by-step.
* **AI Coding Mentors**: Ask context-specific project questions and get beginner-friendly explanations with logic challenges.
* **Supabase User & Session Telemetry**: Secured via Row-Level Security (RLS) database constraints using private backend keys.
* **Google Sheets Webhook Sync**: Syncs code execution details, AI hint usage, and user session metrics in real-time to separate, automatically styled tabs inside your Google Spreadsheet.

---

## 💻 Local Setup & Development

### 1. Prerequisites
- Python 3.10+
- A Google Sheet (optional, for webhook logger)
- A Supabase Project (optional, for cloud database logs)

### 2. Installation
Clone the repository and install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Environment Variables
Create a `.env` file in the root directory and define the following variables:
```env
SECRET_KEY=your_secret_flask_key
USE_SUPABASE=true
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_service_role_key
GOOGLE_SCRIPT_URL=your_google_apps_script_url
GEMINI_API_KEY=your_gemini_api_key
```

### 4. Running Locally
Start the development server:
```bash
python app.py
```
Open **[http://127.0.0.1:5000](http://127.0.0.1:5000)** in your browser.

---

## 📦 Deployment on Render

This repository includes a [`render.yaml`](render.yaml) blueprint config. To deploy your own instance:
1. Log in to [Render](https://render.com).
2. Click **New +** &rarr; **Blueprint**.
3. Connect your repository.
4. Input the environment variables when prompted and click **Apply**.
