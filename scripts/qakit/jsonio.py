"""JsonFile: reading and writing the JSON files in the output folder."""
import json
import os

from .errors import QAError


class JsonFile(object):
    @staticmethod
    def load(path, label=None):
        label = label or os.path.basename(path)
        if not os.path.exists(path):
            raise QAError("%s not found at %s" % (label, path))
        try:
            with open(path) as fh:
                return json.load(fh)
        except ValueError as e:
            raise QAError("%s is not valid JSON: %s" % (label, e))

    @staticmethod
    def write(path, data, indent=1):
        with open(path, "w") as fh:
            json.dump(data, fh, indent=indent, default=str)
        return path
