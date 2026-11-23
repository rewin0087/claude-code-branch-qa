"""Business logic for the /branch-qa skill, one concern per module (mostly one class each).

The scripts in the parent directory are thin command-line wrappers around these classes:

  Foundations
    errors.py       QAError: user-facing errors (CLIs print them without a traceback)
    jsonio.py       load_json / write_json
    gitcmd.py       Git: git for one repository, base-branch detection, the branch diff
    sourcefile.py   SourceFile, SourceCache: repo files, snippets, enclosing definitions
    workspace.py    Workspace: the repo + its .branch-qa/<branch>/ output folder and meta.json

  Prepare (prepare.py)
    preparer.py     Preparer, PrepareDigest: branch -> changes, impact map, tooling
    diffparse.py    DiffParser, ChangedFile: changed lines and the symbols they touch
    impact.py       ImpactAnalyzer: layers, signals, routes, callers, entry points, test level per area
    tooling.py      TestRunnerFinder, E2EToolFinder, DevServerFinder
    stacks.py       StackDetector: languages + frameworks from manifests
    dbconfig.py     DbConfigReader: database settings, credentials redacted

  Ticket (ticket.py)
    ticket.py       TicketSource (inline / file / URL / issue id), TicketParser (requirements)

  Running scenarios
    testrun.py      TestRun, EnvGuard, JUnitParser, OutputParser          (run_tests.py)
    httpcheck.py    HttpCheckRunner, LocalHttpClient, Matcher, JsonPath   (http_check.py)
    uicheck.py      UiCheckRunner, Locator, ScenarioRecorder              (ui_check.py)
    tracelog.py     TraceLog, TraceDigest: trace_py.py / trace_rb.rb logs (trace_digest.py)
    masking.py      RowMasker: secrets redacted, personal data masked

  Render (render.py)
    renderer.py     Renderer: validate + build report.html, summary.md, ticket comment
    vocabulary.py   the enums of qa.json
    validator.py    QAValidator
    summary.py      ResultRows, SummaryWriter (chat), TicketFormats (markdown / jira / plain)
    snippets.py     SnippetCollector: source code embedded in the report
    report.py       ReportBuilder: templates/report.html + embedded JSON
"""
from .errors import QAError

__all__ = ["QAError"]
