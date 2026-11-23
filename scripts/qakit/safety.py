"""The guard rails: where /branch-qa may send requests, which commands it may run, what it hides.

LocalHosts   only loopback / *.localhost / *.test (plus hosts the user explicitly allows)
EnvGuard     refuses commands aimed at production or at a non-local database
Redactor     hides secret-looking values in request/response data and step descriptions
"""
import re

from .errors import QAError


class LocalHosts(object):
    LOOPBACK = ("localhost", "127.0.0.1", "::1", "0.0.0.0")

    def __init__(self, allowed=()):
        self.allowed = tuple(h.lower() for h in allowed)

    def allows(self, host):
        host = (host or "").lower().strip("[]")
        return host in self.LOOPBACK or host.endswith(".localhost") or host.endswith(".test") or host in self.allowed


class EnvGuard(object):
    PROD = re.compile(r"\b(RAILS_ENV|RACK_ENV|NODE_ENV|APP_ENV|DJANGO_ENV|FLASK_ENV|ENVIRONMENT|ASPNETCORE_ENVIRONMENT|MIX_ENV)"
                      r"\s*=\s*['\"]?prod(uction)?\b", re.I)
    DB_URL = re.compile(r"\b(DATABASE_URL|DB_HOST|PGHOST|MYSQL_HOST)\s*=\s*['\"]?([^\s'\"]+)")
    LOCAL_DB = re.compile(r"(localhost|127\.0\.0\.1|::1|0\.0\.0\.0|\.local\b|\.test\b|sqlite|^db$|^postgres$|^mysql$|"
                          r"@db[:/]|@postgres[:/]|@mysql[:/])", re.I)

    @classmethod
    def check(cls, cmd_text, env):
        joined = cmd_text + " " + " ".join("%s=%s" % kv for kv in env.items())
        if cls.PROD.search(joined):
            raise QAError("refusing to run: the command targets a production environment")
        for m in cls.DB_URL.finditer(joined):
            if not cls.LOCAL_DB.search(m.group(2)):
                raise QAError("refusing to run: %s points at a non-local database (%s)" % (m.group(1), m.group(2).split("@")[-1][:60]))


class Redactor(object):
    SECRET_KEY = re.compile(r"(pass(wd|word)?|secret|token|api_?key|authorization|cookie|otp|cvv|card)", re.I)
    SECRET_LABEL = re.compile(r"pass|secret|token", re.I)
    MASK = "[redacted]"

    @classmethod
    def data(cls, obj):
        """A copy of JSON-like data with the values of secret-looking keys replaced."""
        if isinstance(obj, dict):
            return {k: (cls.MASK if cls.SECRET_KEY.search(str(k)) and v not in (None, "") else cls.data(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls.data(x) for x in obj]
        return obj

    @classmethod
    def is_secret_field(cls, label):
        """A form field whose value must not be shown (password, token, ...), by its label or selector."""
        return bool(cls.SECRET_LABEL.search(str(label or "")))
