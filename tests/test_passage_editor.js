"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const editor = require("../static/passage_editor.js");
const makeSegments = () => [
  { id: 10, start: 0, end: 3.5, speaker: "A", text: " First sentence. " },
  { id: 11, start: 3.5, end: 8, speaker: "A", text: "Second sentence." },
  { id: 12, start: 8, end: 12, speaker: "A", text: "Third sentence." },
];
const text = (runs) => runs.map((run) => run.text).join("");
const rewrite = (segments, value, marks = {}) => editor.applyEdit(segments, [{ text: value, ...marks }]);
function assertRoundTrip(value, marks = {}) {
  const original = makeSegments(), changed = rewrite(original, value, marks);
  assert.equal(changed.map((segment) => segment.text).join(""), value);
  assert.equal(editor.fromSegments(changed).text, value);
  assert.deepEqual(changed.map(({ id, start, end, speaker }) => ({ id, start, end, speaker })), original.map(({ id, start, end, speaker }) => ({ id, start, end, speaker })));
  changed.forEach((segment) => assert.equal(text(segment.runs), segment.text));
  assert.equal(changed[0].text_join_before, " ");
  assert.deepEqual(changed.slice(1).map((segment) => segment.text_join_before), ["", ""]);
  assert.equal(original[0].text, " First sentence. ");
  return changed;
}
test("legacy segments join trimmed text with one space", () => {
  const passage = editor.fromSegments(makeSegments());
  assert.equal(passage.text, "First sentence. Second sentence. Third sentence.");
  assert.deepEqual(passage.boundaries, [0, 15, 32, 48]);
});
test("whole rewrites preserve Unicode, blank lines and raw edge whitespace exactly", () => {
  for (const value of ["A clearer opening.\n\nSecond line with emphasis. 中文🙂", "  中文🙂\nOlá — mañana 👨‍👩‍👧‍👦  ", "a", "", " \n "]) assertRoundTrip(value, { bold: true, italic: true });
});
test("shortening leaves empty slices without introducing placeholder text", () => {
  const changed = assertRoundTrip("x");
  assert.ok(changed.some((segment) => segment.text === ""));
  assert.ok(!editor.fromSegments(changed).text.includes("[No text]"));
  assertRoundTrip("");
});
test("minor correction retains unaffected segment words and timing", () => {
  const original = makeSegments();
  const changed = rewrite(original, "First sentence. Better sentence. Third sentence.");
  assert.equal(changed[0].text, "First sentence.");
  assert.equal(changed[2].text, " Third sentence.");
  assert.equal(changed[1].text, " Better sentence.");
});
test("style-only changes and repeated input retain exact characters and marks", () => {
  const first = rewrite(makeSegments(), "Hello 🙂 world\n\n中文", { bold: true });
  const next = editor.applyEdit(first, [{ text: "Hello ", italic: true }, { text: "🙂 world\n\n中文", underline: true }]);
  const roundtrip = editor.fromSegments(next);
  assert.equal(roundtrip.text, "Hello 🙂 world\n\n中文");
  assert.deepEqual(roundtrip.runs, [{ text: "Hello ", bold: false, italic: true, underline: false }, { text: "🙂 world\n\n中文", bold: false, italic: false, underline: true }]);
  assert.equal(editor.fromSegments(editor.applyEdit(next, roundtrip.runs)).text, roundtrip.text);
});
test("mapping uses Unicode code points and retains all IDs after long rewrite", () => {
  const value = "🙂中文 ".repeat(400);
  const changed = assertRoundTrip(value);
  assert.equal(Array.from(editor.fromSegments(changed).text).length, Array.from(value).length);
  changed.forEach((segment) => assert.ok(!/[\uD800-\uDBFF]$/.test(segment.text)));
});
test("empty passage can be filled again without losing segment identities", () => {
  const empty = rewrite(makeSegments(), "");
  const filled = rewrite(empty, "New words 中文🙂");
  assert.equal(editor.fromSegments(filled).text, "New words 中文🙂");
  assert.deepEqual(filled.map((segment) => segment.id), [10, 11, 12]);
});
const txt = (value) => ({ nodeType: 3, nodeValue: value });
const el = (tag, children = [], style = {}) => ({ nodeType: 1, tagName: tag.toUpperCase(), childNodes: children, style });
test("DOM serializer keeps browser-created paragraphs and blank lines", () => {
  assert.equal(text(editor.readEditor(el("div", [txt("Opening."), el("div", [el("br")]), el("div", [txt("Second. 中文🙂")])]))), "Opening.\n\nSecond. 中文🙂");
  assert.equal(text(editor.readEditor(el("div", [el("div", [txt("a")]), el("div", [txt("b")])]))), "a\nb");
  assert.equal(text(editor.readEditor(el("div", [txt("a"), el("br"), el("br")]))), "a\n");
  assert.equal(text(editor.readEditor(el("div", [el("br")]))), "");
  assert.equal(text(editor.readEditor(el("div", [el("div", [txt("one"), el("br")]), el("div", [txt("two")])]))), "one\ntwo");
});
const fs = require("node:fs");
const vm = require("node:vm");
function appHarness() {
  const source = fs.readFileSync(require.resolve("../static/app.js"), "utf8");
  const section = source.slice(source.indexOf("  function transcriptSegmentText("), source.indexOf("  function renderTranscript("));
  const state = { job: { id: "test-recording", status: "complete", segments: makeSegments(), speakers: [{ id: "A", name: "Alex" }, { id: "B", name: "Jordan" }] }, dirty: false };
  const editors = [];
  const context = { state, passage: editor, activeStatuses: new Set(["processing", "queued"]),
    document: { querySelectorAll: (selector) => selector === ".passage-editor" ? editors : [] },
    markDirty: () => { state.dirty = true; }, updateNotesButton() {}, renderJob() {}, toast() {},
    speakerList: () => state.job.speakers, speakerName: (speaker) => speaker.name, speakerIndex: () => 0,
  };
  vm.createContext(context);
  vm.runInContext(section + "\nthis.methods = { groupTranscriptSegments, collectVisibleEdits, assignTranscriptParts };", context);
  return { ...context.methods, state, editors };
}
test("paragraph grouping preserves long raw fragments while enforcing speaker and pause boundaries", () => {
  const { groupTranscriptSegments } = appHarness();
  const parts = rewrite(makeSegments(), "Long passage 中文🙂 ".repeat(150));
  assert.equal(groupTranscriptSegments(parts).length, 1);
  assert.equal(groupTranscriptSegments([...parts, { id: 13, speaker: "A", start: 12, end: 14, text: "Next passage." }]).length, 2);
  assert.equal(groupTranscriptSegments(parts.map((part, index) => ({ ...part, speaker: index ? "B" : "A" }))).length, 2);
  assert.equal(groupTranscriptSegments(parts.map((part, index) => ({ ...part, start: index ? part.start + 8 : part.start, end: index ? part.end + 8 : part.end }))).length, 2);
});
test("assignment collects a pending rich passage against current state without losing text, IDs or names", () => {
  const harness = appHarness();
  const source = harness.state.job.segments;
  const originalMeta = source.map(({ id, start, end }) => ({ id, start, end }));
  const box = el("div", [txt("Pending whole passage.\n\n中文🙂")]);
  box.dataset = { jobId: "test-recording", segmentIds: JSON.stringify(source.map((part) => part.id)), signature: JSON.stringify(editor.fromSegments(source).runs) };
  box.closest = () => null;
  harness.editors.push(box);
  harness.state.job = { ...harness.state.job, segments: source.map((part) => ({ ...part })) };
  harness.assignTranscriptParts([10, 11, 12], "B", "test-recording");
  const current = harness.state.job.segments;
  assert.equal(editor.fromSegments(current).text, "Pending whole passage.\n\n中文🙂");
  assert.deepEqual(current.map(({ id, start, end }) => ({ id, start, end })), originalMeta);
  assert.ok(current.every((part) => part.speaker === "B"));
  assert.deepEqual(harness.state.job.speakers.map((person) => person.name), ["Alex", "Jordan"]);
  assert.equal(harness.state.dirty, true);
  current.forEach((part) => assert.equal(text(part.runs), part.text));
});
test("DOM serializer understands nested formatting and explicit off styles", () => {
  const dom = el("div", [el("strong", [txt("on"), el("span", [txt("off")], { fontWeight: "normal" }), el("span", [txt("also off")], { fontWeight: "400" })]), el("em", [el("span", [txt("plain")], { fontStyle: "normal" })]), el("u", [el("span", [txt("not underlined")], { textDecoration: "none" })])]);
  const runs = editor.readEditor(dom);
  assert.equal(runs[0].bold, true);
  assert.equal(runs[1].bold, false);
  assert.equal(runs[1].italic, false);
  assert.equal(runs[1].underline, false);
  assert.equal(text(runs), "onoffalso offplainnot underlined");
});
test("script content is not serialized and renderer creates only safe nodes", () => {
  const value = "<img src=x onerror=alert(1)> 中文🙂";
  assert.equal(text(editor.readEditor(el("div", [txt(value), el("script", [txt("bad()")])]))), value);
  const documentObject = {
    createTextNode: txt,
    createElement(tag) { const result = el(tag); result.append = (...children) => result.childNodes.push(...children); return result; },
  };
  const container = el("div");
  container.replaceChildren = (...children) => { container.childNodes = children; };
  container.append = (...children) => container.childNodes.push(...children);
  const runs = editor.normalizeRuns([{ text: value, bold: true, italic: true, underline: true }], value);
  editor.renderRuns(container, runs, documentObject);
  assert.deepEqual(editor.readEditor(container), runs);
  assert.equal(container.childNodes[0].tagName, "STRONG");
});
