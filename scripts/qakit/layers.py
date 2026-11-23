"""What kind of code a changed file is, and what its changed lines do.

LayerClassifier  a path (and its content) -> layer: endpoint, route, ui, model, service, job, external, ...
SignalScanner    added lines -> signals (external HTTP, async jobs, callbacks, validation, DB writes,
                 transactions, auth, forms, UI -> API calls, mail, feature flags) and the API calls a UI makes
"""
import re

LAYERS = [
    ("test", r"(^|/)(spec|tests?|__tests__|e2e|cypress|playwright)/|(_spec\.rb|_test\.(rb|py|go)|\.(test|spec)\.[cm]?[jt]sx?|Test\.(java|kt|php|cs))$|(^|/)test_[^/]+\.py$"),
    ("migration", r"(^|/)(db/migrate|migrations|alembic/versions|prisma/migrations|db/migration|database/migrations)/"),
    ("schema", r"(^|/)(db/schema\.rb|db/structure\.sql|schema\.prisma|schema\.sql)$"),
    ("route", r"(^|/)(config/routes\.rb|config/routes/.+\.rb|urls\.py|routes\.(php|[jt]s|py|go)|routes/.+\.(php|[jt]s|py|rb)|router\.[jt]s)$"),
    ("endpoint", r"(^|/)(app/controllers/|app/api/.+/route\.[jt]s$|pages/api/|app/graphql/|resolvers?/|handlers?/)|"
                 r"([Cc]ontroller\.(java|kt|cs|php|[jt]s)|\.controller\.ts|_controller\.rb|views\.py|viewsets?\.py|api\.py|_handler\.go|endpoints?\.py)$"),
    ("ui", r"\.(tsx|jsx|vue|svelte|erb|haml|slim|html|hbs|ejs|twig|blade\.php|css|scss)$|(^|/)(app/views|app/javascript|app/frontend|components|pages|templates|frontend|client|web/src)/"),
    ("validation", r"(^|/)(validators?|serializers?|forms?|contracts|dto|schemas?|inputs|params|requests)/|"
                   r"(serializers?\.py|forms\.py|schemas?\.py|\.dto\.ts|\.(zod|schema)\.[jt]s|(Request|Dto|Form)\.(java|kt|cs|php))$"),
    ("policy", r"(^|/)(policies|permissions?|abilities|guards|middlewares?|authorization)/|(_policy\.rb|permissions\.py|\.guard\.ts|middleware\.[jt]s)$"),
    ("job", r"(^|/)(app/jobs|app/workers|workers?|jobs|queues?|consumers?|sidekiq|celery)/|(tasks\.py|_job\.rb|_worker\.rb|\.job\.ts|\.worker\.ts|\.processor\.ts)$"),
    ("mailer", r"(^|/)(app/mailers|mailers?|notifications?|notifiers?|emails?)/|(_mailer\.rb|mail\.py|notifications?\.py)$"),
    ("external", r"(^|/)(clients?|integrations?|adapters?|gateways?|connectors?|providers?|webhooks?|api_clients?)/|(_client\.(rb|py|go)|Client\.(java|kt|cs|ts)|\.client\.ts|webhooks?\.py)$"),
    ("callback", r"(^|/)(observers?|listeners?|subscribers?|events?|hooks|signals)/|(signals\.py|_observer\.rb|_listener\.rb|\.subscriber\.ts|\.listener\.ts)$"),
    ("model", r"(^|/)(app/models|models?|entities|entity|domain/models?)/|(models\.py|\.model\.[jt]s|\.entity\.ts|Entity\.(java|kt))$"),
    ("service", r"(^|/)(app/services|services?|interactors?|use_?cases?|operations|commands|domain|lib|app/lib|core|business)/"),
    ("config", r"(^|/)(config|settings|initializers)/|(\.env(\.[\w.-]+)?|settings\.py|\.ya?ml|\.toml|\.ini|Dockerfile|Gemfile(\.lock)?|package(-lock)?\.json|yarn\.lock|requirements[\w.-]*\.txt|pyproject\.toml)$"),
    ("docs", r"\.(md|rst|txt|adoc)$|(^|/)docs?/"),
]
LAYER_RX = [(k, re.compile(r)) for k, r in LAYERS]
CODE_EXT = re.compile(r"\.(rb|py|[cm]?[jt]sx?|go|java|kt|cs|php|ex|exs|rs|scala|vue|svelte)$")
IMPORT_LINE = re.compile(r"^\s*(import|from\s+\S+\s+import|require(_relative)?\b|using\s|include\s)")
ENTRY_LAYERS = ("route", "endpoint", "ui", "job", "callback")

SIGNALS = [
    ("external_http", r"\b(requests\.(get|post|put|patch|delete)|httpx\.|Net::HTTP|Faraday|HTTParty|RestClient|axios\.|got\(|"
                      r"node-fetch|urllib\.request|http\.Client|WebClient|RestTemplate|HttpClient|Http::|Excon|Typhoeus|stripe|Stripe::|twilio|sendgrid|boto3|aws-sdk)\b"),
    ("frontend_api_call", r"\b(fetch\(\s*[`'\"]/|axios\.(get|post|put|patch|delete)\(\s*[`'\"]/|useMutation|useQuery|\$\.ajax|router\.(post|put)|\binertia\.(post|put)|form_with|form_for|simple_form_for|\baction=[\"']/)"),
    ("form", r"(<form\b|onSubmit|handleSubmit|useForm\(|form_with|form_for|simple_form_for|\{% csrf_token %\}|<input\b|<select\b|<textarea\b|v-model|formik|react-hook-form)"),
    ("async_job", r"\b(perform_later|perform_async|perform_in|deliver_later|\.delay\(|apply_async|send_task|enqueue|queue\.add|\.add_job|"
                  r"BackgroundTasks|Thread\.new|Promise\.all|asyncio\.gather|ExecutorService|@Async|run_later|after_commit)\b"),
    ("callback", r"\b(before_|after_|around_)(save|create|update|destroy|commit|validation|action)\b|@receiver\(|post_save|pre_save|"
                 r"@(Pre|Post)(Persist|Update)|@EventListener|\.on\(\s*['\"]|emit\(|publish\(|ActiveSupport::Notifications|dispatch\("),
    ("validation", r"\b(validates?_?\w*|ValidationError|validator|validate|errors\.add|raise .*Invalid|z\.object|Joi\.|yup\.|"
                   r"@Valid|@NotNull|@Size|clean_\w+|serializers\.ValidationError|rules\(|required:\s*true|pattern=)\b"),
    ("db_write", r"\b(save!?|create!?|update!?|update_columns?|destroy!?|delete|insert|upsert|bulk_create|increment!|decrement!|"
                 r"\.objects\.(create|update|filter\(.*\)\.update)|session\.(add|commit|merge)|prisma\.\w+\.(create|update|upsert|delete)|INSERT|UPDATE|DELETE)\b"),
    ("transaction", r"\b(transaction|atomic|with_lock|lock!|select_for_update|FOR UPDATE|\$transaction|BEGIN)\b"),
    ("auth", r"\b(authenticate|authorize|current_user|login_required|permission_classes|before_action :authenticate|"
             r"policy_scope|can\?|cannot\?|has_perm|@PreAuthorize|guard|jwt|session\[)\b"),
    ("mail", r"\b(deliver_now|deliver_later|send_mail|mail\(|EmailMessage|sendgrid|mailer|notify)\b"),
    ("feature_flag", r"\b(Flipper|feature_enabled|flag_enabled|LaunchDarkly|unleash|waffle|feature_flag|FeatureFlag)\b"),
]
SIGNAL_RX = [(k, re.compile(r, re.I if k in ("form",) else 0)) for k, r in SIGNALS]
API_CALL = re.compile(r"""(?:fetch|axios\.(get|post|put|patch|delete)|\$\.ajax|post|put)\(\s*[`'"]([^`'"]*?/[^`'"]*)[`'"]""")
ACTION_ATTR = re.compile(r"""\baction=["']([^"'{}]+)["']|url:\s*['"]([^'"]+)['"]""")

ROUTING_CODE = re.compile(r"@\w+\.(get|post|put|patch|delete|route|api_route)\(|\b(router|app|server)\.(get|post|put|patch|delete|all|use)\(|"
                          r"\bdo_(GET|POST|PUT|PATCH|DELETE)\b|HandleFunc\(|@(Get|Post|Put|Patch|Delete|Request)Mapping|Route::|"
                          r"\burlpatterns\b|\bBaseHTTPRequestHandler\b|\bAPIRouter\(|\bBlueprint\(")


class LayerClassifier(object):
    @staticmethod
    def refine(path, layer, lines):
        """A 'service' / 'other' file that defines HTTP handlers or routes is an endpoint."""
        if layer in ("service", "other", "config") and CODE_EXT.search(path) and lines and \
                any(ROUTING_CODE.search(l) for l in lines[:3000]):
            return "endpoint"
        return layer

    @staticmethod
    def layer(path):
        for key, rx in LAYER_RX:
            if rx.search(path):
                if key == "ui" and re.search(r"\.(css|scss)$", path):
                    return "style"
                return key
        return "service" if CODE_EXT.search(path) else "other"


class SignalScanner(object):
    @staticmethod
    def scan(lines):
        found = {}
        for text in lines:
            for key, rx in SIGNAL_RX:
                if rx.search(text) and len(found.setdefault(key, [])) < 4:
                    found[key].append(text.strip()[:160])
        return found

    @staticmethod
    def api_calls(lines):
        out = []
        for text in lines:
            for m in API_CALL.finditer(text):
                out.append({"method": (m.group(1) or "").upper() or None, "path": m.group(2)})
            for m in ACTION_ATTR.finditer(text):
                out.append({"method": None, "path": m.group(1) or m.group(2)})
        return out[:10]
