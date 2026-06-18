"""
WSGI entry point for Vercel deployment.
Vercel's Python runtime looks for `app` in this file.
"""
from app import app

# Vercel needs the handler to be named `app`
# Flask app is already named `app`, so this just re-exports it.

if __name__ == "__main__":
    app.run()
