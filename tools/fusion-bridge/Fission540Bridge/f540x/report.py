"""What an import could not do, and why.

Every step of an import is attempted on its own: a feature the API cannot express is
recorded here and the rest of the design still comes across. The report is shown when
the import finishes and written beside the bundle as a log.
"""

import traceback


class Unsupported(Exception):
    """Raised when an entity cannot be rebuilt; the reason goes into the report."""


class Report:
    def __init__(self):
        self.counts = {}
        self.log = []
        self.issues = 0

    def count(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def issue(self, what, why=""):
        self.issues += 1
        self.log.append("ISSUE %s%s" % (what, (": " + str(why)) if why else ""))

    def note(self, text):
        self.log.append("note  " + str(text))

    def failure(self, what):
        """An unexpected exception: keep the traceback, it is the only clue available."""
        self.issues += 1
        self.log.append("ERROR %s\n%s" % (what, traceback.format_exc()))

    def text(self, source):
        lines = ["Imported " + source, ""]
        for key in sorted(self.counts):
            lines.append("%s: %d" % (key, self.counts[key]))
        if self.issues:
            lines.append("")
            lines.append("%d item(s) need attention, see the import log. First ones:" % self.issues)
            problems = [line for line in self.log if not line.startswith("note")]
            lines.extend(line.splitlines()[0] for line in problems[:10])
        else:
            lines.append("")
            lines.append("No problems reported.")
        return "\n".join(lines)

    def log_text(self):
        return "\n".join(self.log) + "\n"
