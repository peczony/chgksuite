import os
import webbrowser
from threading import Timer

from flask import Flask, request, render_template_string

from chgksuite.ui_gen import render_ui

app = Flask("chgksuite", static_folder="resources")
PORT = 1992


@app.route("/", methods=["GET", "POST"])
def route():
    if request.form:
        print(request.form.to_dict())
    return render_template_string(render_ui())


def open_browser():
    webbrowser.open_new_tab(f"http://localhost:{PORT}")


def run_app():
    Timer(1, open_browser).start()
    app.run(host="0.0.0.0", port=PORT, debug=bool(os.environ.get("DEBUG")))


if __name__ == "__main__":
    run_app()
