# coding: utf-8
# SPDX-License-Identifier: GPL-3.0-or-later
# Python 2.7 旧版 Pylint 子进程入口。
# Python 2.7 legacy Pylint worker process entry point.

"""Run Pylint 1.9.5 under the real Python 2.7 interpreter.

This file intentionally remains Python 2.7-compatible.  The parent Python 3
process sends a JSON document on stdin so a large pack never exceeds the
Windows command-line length limit.
"""

from __future__ import absolute_import, print_function

import cgi
import json
import sys
import traceback

from pylint.interfaces import IReporter
from pylint.reporters import BaseReporter


STRING_TYPES = (basestring,)


def _as_unicode(value):
    if isinstance(value, unicode):
        return value
    if not isinstance(value, str):
        return unicode(value)
    return value.decode("utf-8", "replace")


class CollectingReporter(BaseReporter):
    __implements__ = IReporter

    def __init__(self):
        BaseReporter.__init__(self, sys.stdout)
        self.messages = []

    def handle_message(self, message):
        self.messages.append({
            "type": _as_unicode(message.category),
            "module": _as_unicode(message.module),
            "obj": _as_unicode(message.obj),
            "line": message.line,
            "column": message.column,
            "path": _as_unicode(message.path),
            "symbol": _as_unicode(message.symbol),
            "message": _as_unicode(cgi.escape(message.msg or "")),
            "message-id": _as_unicode(message.msg_id),
        })

    def display_messages(self, layout):
        pass

    def display_reports(self, layout):
        pass

    def _display(self, layout):
        pass


def _string_list(payload, key):
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, STRING_TYPES) for item in value):
        raise ValueError("%s 必须是字符串列表" % key)
    return value


def _skip_disabled_python3_cmp_check():
    """Avoid a Pylint 1.9.5 crash for a disabled W1640 check."""

    from pylint.checkers.python3 import Python3Checker

    original = Python3Checker._check_cmp_argument

    def guarded(checker, node):
        if not checker.linter.is_message_enabled("using-cmp-argument"):
            return None
        return original(checker, node)

    Python3Checker._check_cmp_argument = guarded


def _write_event(payload):
    json.dump(payload, sys.stdout, ensure_ascii=True, separators=(",", ":"))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _run(payload, file_completed=None):
    files = _string_list(payload, "files")
    message_ids = _string_list(payload, "message_ids")
    ignored_message_ids = _string_list(payload, "ignored_message_ids")
    if not files:
        return []

    from pylint.lint import PyLinter, Run
    _skip_disabled_python3_cmp_check()
    reporter = CollectingReporter()
    arguments = [
        "--disable=all",
        "--enable=" + ",".join(message_ids),
    ]
    if ignored_message_ids:
        arguments.append("--disable=" + ",".join(ignored_message_ids))
    arguments.extend(["--reports=no", "--score=no", "--persistent=no"])
    arguments.extend(files)

    original_expand_files = PyLinter.expand_files

    def expand_files_with_progress(linter, modules):
        previous = None
        for descriptor in original_expand_files(linter, modules):
            if previous is not None and file_completed is not None:
                file_completed(previous["path"])
            previous = descriptor
            yield descriptor
        if previous is not None and file_completed is not None:
            file_completed(previous["path"])

    # Pylint 1.9.5 has no --py-version option.  Since this process is running
    # in Python 2.7, astroid naturally parses and infers Python 2 semantics.
    PyLinter.expand_files = expand_files_with_progress
    try:
        Run(arguments, reporter=reporter, exit=False)
    finally:
        PyLinter.expand_files = original_expand_files
    return reporter.messages


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("输入 JSON 顶层不是对象")
        result = _run(
            payload,
            file_completed=lambda path: _write_event({
                "type": "progress",
                "path": _as_unicode(path),
            }),
        )
        _write_event({"type": "result", "messages": result})
        return 0
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
