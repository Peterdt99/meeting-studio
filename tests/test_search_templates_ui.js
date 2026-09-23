"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(require.resolve("../static/app.js"), "utf8");
class Element {
  constructor(tag = "div", className = "", text = "") {
    this.tagName = tag; this.className = className; this.children = []; this.dataset = {}; this.attributes = {}; this.value = ""; this.open = false; this._text = String(text); this.listeners = {};
    this.classList = { toggle() {}, contains: () => false, add() {}, remove() {} };
  }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() { this.focused = true; }
  get childElementCount() { return this.children.filter((child) => typeof child !== "string").length; }
  get textContent() { return this._text + this.children.map((child) => typeof child === "string" ? child : child.textContent).join(""); }
  set textContent(value) { this._text = String(value); this.children = []; }
}
function harness(api = async () => ({})) {
  const elements = new Map();
  const $ = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const state = { job: null, selectedId: null, dirty: false, noteTemplates: [], selectionRequest: 0, collectionVersion: 0, searchRequest: 0, searchQuery: "", searchResults: [], searchTotal: 0, searchHasMore: false, searchLoading: false, searchError: "", searchOpening: false };
  const calls = { selections: [], jumps: [], toasts: [], collections: 0 };
  const context = { state, $, api, node: (tag, cls, text) => new Element(tag, cls, text), show: (element, visible = true) => { element.visible = visible; }, clearTimeout() {},
    activeStatuses: new Set(["queued", "processing"]), timestamp: (start) => `0:${String(start).padStart(2, "0")}`,
    collectVisibleEdits: () => { ++calls.collections; }, updateNotesButton() {}, renderDirty() {},
    toast: (...args) => calls.toasts.push(args),
    selectJob: async (id) => { calls.selections.push(id); state.selectedId = id; state.job = { id, segments: [{ id: 4, start: 10 }] }; return true; },
    jumpToSegment: (segment) => calls.jumps.push(segment), groupTranscriptSegments: () => [], speakerList: () => [], passage: {},
  };
  const fallback = source.slice(source.indexOf("  const fallbackTemplates ="), source.indexOf("  const activeStatuses ="));
  const functions = source.slice(source.indexOf("  function renderSearch("), source.indexOf("  function clearSelectedJob("));
  const notes = source.slice(source.indexOf("  function renderNotes("), source.indexOf("  function setTab("));
  vm.createContext(context);
  vm.runInContext(fallback + functions + notes + "\nthis.methods = { renderSearch, searchRecordings, requestSearchResult, openSearchResult, noteTemplate, renderTemplatePicker, changeNotesTemplate, renderNotes };", context);
  return { ...context.methods, state, $, calls, context };
}
const result = (extra = {}) => ({ job_id: "other", title: "Lecture example", segment_id: 4, start: 10, snippet: "🙂 budget decision today", match_start: 3, match_end: 18, ...extra });
test("search ignores an older result after a newer query wins", async () => {
  const pending = [];
  const h = harness((path) => new Promise((resolve) => pending.push({ path, resolve })));
  h.$("recording-search").value = "old"; const first = h.searchRecordings();
  h.$("recording-search").value = "budget decision"; const second = h.searchRecordings();
  pending[1].resolve({ results: [result()], total: 1, has_more: false }); await second;
  pending[0].resolve({ results: [result({ title: "Obsolete" })], total: 1, has_more: false }); await first;
  assert.equal(h.state.searchResults[0].title, "Lecture example");
  assert.equal(h.state.searchLoading, false);
  assert.match(pending[1].path, /budget%20decision/);
});
test("pagination appends matches and requests the next offset", async () => {
  const paths = [];
  const h = harness(async (path) => { paths.push(path); return paths.length === 1 ? { results: Array.from({ length: 50 }, (_, i) => result({ segment_id: i })), total: 51, has_more: true } : { results: [result({ segment_id: 50 })], total: 51, has_more: false }; });
  h.$("recording-search").value = "budget"; await h.searchRecordings(); await h.searchRecordings(true);
  assert.match(paths[1], /offset=50$/); assert.equal(h.state.searchResults.length, 51); assert.equal(h.state.searchHasMore, false);
});
test("empty query makes no request and failed search remains retryable", async () => {
  let calls = 0;
  const h = harness(async () => { ++calls; throw new Error("Offline"); });
  h.$("recording-search").value = "   "; await h.searchRecordings(); assert.equal(calls, 0);
  h.$("recording-search").value = "budget"; await h.searchRecordings();
  assert.equal(calls, 1); assert.equal(h.state.searchLoading, false); assert.match(h.state.searchError, /Offline/);
});
test("snippets use UTF-16 offsets and safe text nodes", () => {
  const h = harness(); h.state.searchResults = [result({ title: "<script>bad()</script>" })]; h.renderSearch();
  const button = h.$("search-results").children[0], snippet = button.children[2];
  assert.equal(button.children[0].textContent, "<script>bad()</script>");
  assert.equal(snippet.children[1].tagName, "mark"); assert.equal(snippet.children[1].textContent, "budget decision");
  assert.equal(snippet.textContent, "🙂 budget decision today");
});
test("opening another recording with unsaved edits waits for an explicit Save and open", () => {
  const h = harness(); h.state.job = { id: "current", segments: [{ id: 1, text: "draft" }] }; h.state.selectedId = "current"; h.state.dirty = true;
  h.requestSearchResult(result());
  assert.equal(h.$("search-unsaved-dialog").open, true); assert.equal(h.$("cancel-search-open").focused, true);
  assert.equal(h.state.job.segments[0].text, "draft"); assert.equal(h.state.dirty, true); assert.equal(h.calls.selections.length, 0);
});
test("same-recording result keeps its unsaved draft and seeks its existing source", async () => {
  const h = harness(); h.state.job = { id: "other", segments: [{ id: 4, start: 10, text: "draft" }] }; h.state.selectedId = "other"; h.state.dirty = true;
  await h.openSearchResult(result());
  assert.equal(h.calls.selections.length, 0); assert.equal(h.calls.jumps[0].start, 10); assert.equal(h.state.dirty, true); assert.equal(h.state.job.segments[0].text, "draft");
});
test("template-only save preserves rich transcript drafts and invalidates older polling", async () => {
  const requests = [];
  const h = harness(async (path, options) => { requests.push(JSON.parse(options.body)); return { notes_template: "lecture", notes_stale: true }; });
  const segments = [{ id: 4, text: "Unchanged 中文🙂", runs: [{ text: "Unchanged 中文🙂", bold: true }] }];
  h.state.job = { id: "current", notes_template: "meeting", segments, notes: { template: "meeting", overview: "Summary", decisions: [], actions: [], open_questions: [] } }; h.state.dirty = true;
  h.$("notes-template").value = "lecture"; await h.changeNotesTemplate();
  assert.deepEqual(requests, [{ notes_template: "lecture" }]); assert.equal(h.state.job.segments, segments); assert.equal(h.state.dirty, true);
  assert.equal(h.state.selectionRequest, 2); assert.equal(h.state.job.notes_template, "lecture"); assert.equal(h.state.job.notes.template, "meeting"); assert.equal(h.state.templateSaving, false);
});
test("saved note metadata controls section labels until regeneration, with summary first", () => {
  const h = harness();
  h.state.job = { id: "current", notes_template: "lecture", segments: [], notes: { overview: "Keep this summary", decisions: [{ text: "Keep this decision" }], actions: [], open_questions: [] } };
  h.renderNotes();
  const content = h.$("notes-content");
  assert.equal(content.children[0].children[0].textContent, "Summary"); assert.equal(content.children[1].children[0].textContent, "Decisions");
  assert.equal(content.children.at(-1).children[0].textContent, "Full transcript"); assert.match(h.$("notes-state").textContent, /Regenerate notes to use lecture notes/);
  h.state.job.notes.template = "lecture"; h.renderNotes(); assert.equal(h.$("notes-content").children[1].children[0].textContent, "Key concepts");
  h.state.job.notes.template = "journal"; h.renderNotes(); assert.equal(h.$("notes-content").children[1].children[0].textContent, "Highlights & reflections");
});
test("failed template save restores the previous choice without clearing the draft", async () => {
  const h = harness(async () => { throw new Error("Save failed"); });
  h.state.job = { id: "current", notes_template: "meeting", segments: [{ id: 1, text: "draft" }] }; h.state.dirty = true;
  h.$("notes-template").value = "journal"; await h.changeNotesTemplate();
  assert.equal(h.state.job.notes_template, "meeting"); assert.equal(h.state.dirty, true); assert.equal(h.state.job.segments[0].text, "draft"); assert.equal(h.state.templateSaving, false); assert.equal(h.calls.toasts.length, 1);
});
