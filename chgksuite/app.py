import os
import webbrowser
from threading import Timer

from flask import Flask, render_template_string

from chgksuite.ui_gen import render_ui

app = Flask("chgksuite", static_folder="resources")
PORT = 1992


@app.route("/")
def route():
    return render_template_string(render_ui())


def open_browser():
    webbrowser.open_new_tab(f"http://localhost:{PORT}")


def run_app():
    Timer(2, open_browser).start()
    app.run(host="0.0.0.0", port=PORT, debug=bool(os.environ.get("DEBUG")))


if __name__ == "__main__":
    run_app()
