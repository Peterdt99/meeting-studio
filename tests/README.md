# Regression checks

From the app root, install requirements-dev.txt into a Python 3.12 environment,
then run `python -m pytest tests -q`. With Node.js 24 installed, also run
`node --test tests/test_passage_editor.js tests/test_search_templates_ui.js`
for rich text, search navigation and template presentation checks.
No npm packages are needed. Node.js is a development prerequisite only; the
installed app runs its interface in WebView2 or a browser.

Tests use synthetic data and mocked background jobs. They do not download models,
contact Ollama, or alter the recording library. The installed-model catalog check
is optional and skips when models are absent. Windows may also skip creating a
real symlink if the account lacks permission; a simulated reparse-point test still
checks that linked files are rejected before deletion.

The passage tests check exact text and formatting round trips, Unicode, blank
lines, empty slices, preserved source identifiers and safe rendering. Search and
template tests cover transcript matches, saved-note provenance and export headings. Both the
Python suite and Node.js tests run in the Windows build workflow.

Temporary test state and generated synthetic examples must never be committed.
