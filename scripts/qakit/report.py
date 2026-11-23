"""The HTML report file.

ReportBuilder  templates/report.html + the embedded JSON payload -> one self-contained page
ReportOpener   opens it in the default browser (macOS / Windows / Linux)
"""
import json
import os
import subprocess
import sys

from .errors import QAError
from .text import Text

DEFAULT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates", "report.html")
DATA_PLACEHOLDER, TITLE_PLACEHOLDER = "__QA_DATA__", "__TITLE__"


class ReportBuilder(object):
    def __init__(self, template_path=DEFAULT_TEMPLATE):
        self.template_path = template_path

    @staticmethod
    def embed_json(obj):
        """JSON that is safe to place inside a <script> element."""
        return json.dumps(obj, default=str).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    def build(self, payload):
        with open(self.template_path) as fh:
            html = fh.read()
        if DATA_PLACEHOLDER not in html:
            raise QAError("template is missing the %s placeholder" % DATA_PLACEHOLDER)
        html = html.replace(DATA_PLACEHOLDER, self.embed_json(payload), 1)
        return html.replace(TITLE_PLACEHOLDER, Text.html_escape(payload["qa"].get("title", "QA report")), 1)


class ReportOpener(object):
    @staticmethod
    def open(path):
        """Best effort: returns an error message instead of raising."""
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform.startswith("win"):
                os.startfile(path)  # noqa
            else:
                subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return None
        except Exception as e:      # noqa
            return "Could not open browser automatically: %s" % e
