"""Make `tests` a real package rather than an implicit namespace package.

THIS FILE IS LOAD-BEARING, NOT BOILERPLATE. Deleting it breaks collection with
``ModuleNotFoundError: No module named 'tests.test_api_apply'`` and pytest exits
with code 2 before running a single test.

``tests/test_submit_dryrun.py`` reuses submit scaffolding via
``from tests.test_api_apply import ...``. Without an ``__init__.py`` here,
``tests`` is only a namespace *portion*: Python's path finder records it and
keeps scanning ``sys.path``, and the first REGULAR package named ``tests`` wins
outright. Two of this project's dependencies install one — ``crawl4ai==0.3.74``
and ``playwright-stealth==1.0.6`` both ship a top-level ``tests/`` containing an
``__init__.py`` — so the import resolves inside site-packages instead of here.

The failure is invisible in a minimal dev environment and only appears once the
full ``requirements.txt`` is installed, which is exactly what CI does. Verified
in both directions: absent → exit code 2 during collection; present → the whole
suite collects and passes. ``TestSuiteImportHygiene`` in
``tests/test_suite_hermeticity.py`` pins it.
"""
