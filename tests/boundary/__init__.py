"""Stage 2.9 canonical boundary tier (per SUBPROJECT_TESTING_STANDARD §2).

§10 red lines as boundary tests:
- Approved-source-only enforcement (CLAUDE.md #1).
- Evidence span mandatory on all Ex candidates (CLAUDE.md #5).
- No-business-import deny scan on subsystem_news.public (no
  data_platform / main_core / graph_engine / audit_eval / orchestrator;
  no openai / anthropic / litellm direct provider SDK; no second parser
  beyond approved RSS/API/HTML adapters).
- Iron rule #7: SDK wire-shape boundary (envelope strip via real adapter).

Iron rule #2: deny-scan boundary tests use ``subprocess.run`` for
isolation — sys.modules pollution from earlier collected tests would
mask real import-graph leaks otherwise.
"""
