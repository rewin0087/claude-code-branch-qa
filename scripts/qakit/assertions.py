"""Checking actual values against expectations (http_check / ui_check specs).

JsonPath  `a.b[0].c` / `a.b.0.c` lookups into parsed JSON
Matcher   a plain value (equality) or operators: $exists $ne $contains $regex $gt $gte $lt $lte $len $type $in
"""
import json
import re

from .errors import QAError


class JsonPath(object):
    @staticmethod
    def get(data, path):
        """-> (found, value)"""
        cur = data
        if path in ("", "$", "."):
            return True, data
        for part in re.findall(r"[^.\[\]]+", path):
            if isinstance(cur, list) and re.match(r"^-?\d+$", part):
                i = int(part)
                if -len(cur) <= i < len(cur):
                    cur = cur[i]
                    continue
                return False, None
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
                continue
            return False, None
        return True, cur


class Matcher(object):
    TYPES = {"string": str, "number": (int, float), "bool": bool, "null": type(None), "list": list, "object": dict}

    @classmethod
    def check(cls, expected, found, actual):
        """-> (ok, description of the expectation)"""
        if isinstance(expected, dict) and expected and all(k.startswith("$") for k in expected):
            for op, v in expected.items():
                if not cls._op(op, v, found, actual):
                    return False, "%s %s" % (op, json.dumps(v))
            return True, " ".join("%s %s" % (k, json.dumps(v)) for k, v in expected.items())
        return found and actual == expected, "== %s" % json.dumps(expected, default=str)

    @classmethod
    def _op(cls, op, v, found, actual):
        try:
            if op == "$exists":
                return found == bool(v) and (not v or actual is not None)
            if not found and op != "$ne":
                return False
            if op == "$ne":
                return actual != v
            if op == "$contains":
                return (v in actual) if isinstance(actual, (list, dict)) else str(v).lower() in str(actual).lower()
            if op == "$regex":
                return re.search(v, str(actual)) is not None
            if op == "$gt":
                return actual > v
            if op == "$gte":
                return actual >= v
            if op == "$lt":
                return actual < v
            if op == "$lte":
                return actual <= v
            if op == "$len":
                return len(actual) == v
            if op == "$type":
                return isinstance(actual, cls.TYPES[v]) and not (v == "number" and isinstance(actual, bool))
            if op == "$in":
                return actual in v
        except (TypeError, KeyError):
            return False
        raise QAError("unknown matcher %s" % op)
