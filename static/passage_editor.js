(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.MeetingPassageEditor = api;
})(typeof globalThis === "object" ? globalThis : this, function () {
  "use strict";
  const points = (text) => Array.from(String(text ?? ""));
  const flags = (run) => ({ bold: run.bold === true, italic: run.italic === true, underline: run.underline === true });
  function appendRun(runs, text, marks = {}) {
    if (!text) return;
    const style = flags(marks);
    const last = runs[runs.length - 1];
    if (last && last.bold === style.bold && last.italic === style.italic && last.underline === style.underline) last.text += text;
    else runs.push({ text, ...style });
  }
  function normalizeRuns(runs, fallback = "") {
    const result = [];
    if (Array.isArray(runs)) for (const run of runs) if (run && typeof run.text === "string") appendRun(result, run.text, run);
    if (result.map((run) => run.text).join("") !== fallback) return fallback ? [{ text: fallback, ...flags({}) }] : [];
    return result;
  }
  function sliceRuns(runs, start, end) {
    const result = [];
    let offset = 0;
    for (const run of runs) {
      const chars = points(run.text);
      const from = Math.max(0, start - offset), to = Math.min(chars.length, end - offset);
      if (from < to) appendRun(result, chars.slice(from, to).join(""), run);
      offset += chars.length;
    }
    return result;
  }
  function segmentDisplay(segment) {
    const raw = String(segment.text ?? "");
    const explicit = segment.text_join_before === "" || segment.text_join_before === " ";
    const text = explicit ? raw : raw.trim();
    let runs = normalizeRuns(segment.runs, raw);
    if (!explicit) {
      const start = points(raw).length - points(raw.trimStart()).length;
      runs = sliceRuns(runs, start, start + points(text).length);
    }
    return { text, runs, joinBefore: explicit ? segment.text_join_before : " " };
  }
  function fromSegments(segments) {
    const runs = [], boundaries = [0];
    let length = 0;
    segments.forEach((segment, index) => {
      const display = segmentDisplay(segment);
      if (index) { appendRun(runs, display.joinBefore); length += points(display.joinBefore).length; }
      for (const run of display.runs) appendRun(runs, run.text, run);
      length += points(display.text).length;
      boundaries.push(length);
    });
    return { text: runs.map((run) => run.text).join(""), runs, boundaries };
  }
  function mapBoundaries(oldText, newText, boundaries) {
    const oldChars = points(oldText), newChars = points(newText);
    if (oldText === newText) return [...boundaries];
    if (!oldChars.length) return boundaries.map((_, index) => index ? newChars.length : 0);
    let prefix = 0;
    while (prefix < oldChars.length && prefix < newChars.length && oldChars[prefix] === newChars[prefix]) ++prefix;
    let suffix = 0;
    while (suffix < oldChars.length - prefix && suffix < newChars.length - prefix && oldChars[oldChars.length - 1 - suffix] === newChars[newChars.length - 1 - suffix]) ++suffix;
    const oldEnd = oldChars.length - suffix, newEnd = newChars.length - suffix;
    const difference = newChars.length - oldChars.length;
    const whiteBoundaries = [];
    for (let i = prefix; i <= newEnd; ++i) if ((i > 0 && /\s/u.test(newChars[i - 1])) || (i < newChars.length && /\s/u.test(newChars[i]))) whiteBoundaries.push(i);
    let previous = 0;
    return boundaries.map((boundary, index) => {
      if (!index) return 0;
      if (index === boundaries.length - 1) return newChars.length;
      let mapped;
      if (boundary <= prefix) mapped = boundary;
      else if (boundary >= oldEnd) mapped = boundary + difference;
      else {
        mapped = prefix + Math.round((boundary - prefix) * (newEnd - prefix) / (oldEnd - prefix));
        if (whiteBoundaries.length) mapped = whiteBoundaries.reduce((best, candidate) => Math.abs(candidate - mapped) < Math.abs(best - mapped) ? candidate : best, whiteBoundaries[0]);
      }
      previous = Math.max(previous, Math.min(newChars.length, mapped));
      return previous;
    });
  }
  function applyEdit(segments, incomingRuns) {
    const text = (incomingRuns || []).map((run) => String(run.text ?? "")).join("");
    const runs = normalizeRuns(incomingRuns, text);
    const old = fromSegments(segments);
    const boundaries = mapBoundaries(old.text, text, old.boundaries);
    const chars = points(text);
    return segments.map((segment, index) => ({
      ...segment,
      text: chars.slice(boundaries[index], boundaries[index + 1]).join(""),
      text_join_before: index ? "" : (segment.text_join_before === "" ? "" : " "),
      runs: sliceRuns(runs, boundaries[index], boundaries[index + 1]),
    }));
  }
  function readEditor(editor) {
    function readChildren(parent, marks) {
      const result = [];
      const children = Array.from(parent.childNodes || []);
      let previousBlock = false, sawNode = false;
      children.forEach((child, index) => {
        if (child.nodeType !== 1 && child.nodeType !== 3) return;
        const tag = String(child.tagName || "").toUpperCase();
        if (["SCRIPT", "STYLE", "NOSCRIPT"].includes(tag)) return;
        const block = ["DIV", "P", "LI", "BLOCKQUOTE"].includes(tag);
        if (sawNode && (block || previousBlock)) {
          const lastText = result[result.length - 1]?.text || "";
          if (previousBlock || !lastText.endsWith("\n")) appendRun(result, "\n", marks);
        }
        if (child.nodeType === 3) appendRun(result, child.nodeValue || "", marks);
        else if (tag === "BR") {
          // A terminal BR keeps an empty browser editing line selectable; it
          // does not add another line after the surrounding block boundary.
          const placeholder = index === children.length - 1;
          if (!placeholder) appendRun(result, "\n", marks);
        } else {
          const style = child.style || {};
          const weight = String(style.fontWeight || "");
          const italic = String(style.fontStyle || "");
          const decoration = String(style.textDecorationLine || style.textDecoration || "");
          const nested = {
            bold: weight ? weight === "bold" || Number(weight) >= 600 : marks.bold || ["B", "STRONG"].includes(tag),
            italic: italic ? italic === "italic" || italic === "oblique" : marks.italic || ["I", "EM"].includes(tag),
            underline: decoration ? decoration.includes("underline") : marks.underline || tag === "U",
          };
          for (const run of readChildren(child, nested)) appendRun(result, run.text, run);
        }
        previousBlock = block;
        sawNode = true;
      });
      return result;
    }
    return readChildren(editor, flags({}));
  }
  function renderRuns(container, runs, documentObject = container.ownerDocument) {
    container.replaceChildren();
    for (const run of runs) {
      let current = documentObject.createTextNode(run.text);
      for (const [mark, tag] of [["underline", "u"], ["italic", "em"], ["bold", "strong"]]) if (run[mark]) { const wrapper = documentObject.createElement(tag); wrapper.append(current); current = wrapper; }
      container.append(current);
    }
  }
  return { normalizeRuns, sliceRuns, segmentDisplay, fromSegments, mapBoundaries, applyEdit, readEditor, renderRuns };
});
