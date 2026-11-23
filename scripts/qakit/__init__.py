"""Business logic for the /branch-qa skill: one concern per module, the logic in classes.

The scripts in the parent directory are thin command-line wrappers: they parse arguments, call
these classes and print what a *Digest / format() method returns.

  Foundations
    errors.py         QAError: user-facing errors (CLIs print them without a traceback)
    jsonio.py         JsonFile: load / write the JSON files in the output folder
    text.py           Text (one-liners, truncation, slugs, line ranges, file URLs), MarkdownTable
    safety.py         LocalHosts (localhost only), EnvGuard (no production / remote DB), Redactor (secrets)
    gitcmd.py         Git: git for one repository, base-branch detection, the branch diff
    sourcefile.py     SourceFile, SourceCache: repo files, snippets, enclosing definitions
    workspace.py      Workspace: the repo + its .branch-qa/<branch>/ output folder and meta.json

  Prepare (prepare.py)
    preparer.py       PrepareOptions, Preparer (orchestration), PrepareDigest (what the agent reads)
    branchchanges.py  BranchChanges: base branch, merge-base, changed + untracked files
    diffparse.py      DiffParser, ChangedFile, SymbolName: changed lines and the symbols they touch
    impact.py         ImpactAnalyzer, TestLevelPlanner: what each change reaches and how to test it
    layers.py         LayerClassifier, SignalScanner: kind of code, what the added lines do
    routes.py         EndpointFinder: routes added, routes reaching changed handlers
    callers.py        CallerFinder: callers, covering tests, entry points
    tooling.py        ToolingSurvey, TestRunnerFinder, E2EToolFinder, DevServerFinder
    stacks.py         StackDetector: languages + frameworks from manifests (or file extensions)
    dbconfig.py       DbConfigReader: database settings, credentials redacted

  Ticket (ticket.py)
    ticket.py         TicketSource (inline / file / URL / issue id), TicketParser, TicketFile, TicketDigest

  Running scenarios
    testrun.py        TestRun, ProcessRunner, JUnitParser, OutputParser, TestRunDigest     (run_tests.py)
    httpcheck.py      HttpCheckRunner, HttpRequestBuilder, SpecVariables, LocalHttpClient,
                      HttpResponse, ResponseChecker, HttpCheckDigest                      (http_check.py)
    uicheck.py        UiCheckRunner, UiSteps, Locator, ScenarioRecorder, Screenshots,
                      StepText, PlaywrightLoader, UiCheckDigest                           (ui_check.py)
    assertions.py     JsonPath, Matcher: expectations shared by the HTTP and UI checks
    tracelog.py       TraceLog, TraceDigest, SqlTables: trace_py.py / trace_rb.rb logs     (trace_digest.py)
    masking.py        RowMasker: secrets redacted, personal data masked

  Render (render.py)
    renderer.py       Renderer, RenderResult: validate + build report.html, summary.md, ticket comment
    validator.py      QAValidator
    vocabulary.py     the enums of qa.json, Outcomes (expected?, requirement status)
    results.py        ResultRows: the results table rows and counts
    summary.py        SummaryWriter: the chat summary
    ticketformats.py  TicketFormats: Markdown / Jira / plain text for the ticket
    snippets.py       SnippetCollector: source code embedded in the report
    report.py         ReportBuilder (template + embedded JSON), ReportOpener

The tracers (trace_py.py, trace_rb.rb) stay single standalone files on purpose, so they run under
the project's own interpreter without importing anything; inside, they are organised in classes.
"""
from .errors import QAError

__all__ = ["QAError"]
