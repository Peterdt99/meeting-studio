"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const passage = window.MeetingPassageEditor;
  const state = {
    jobs: [], selectedId: null, job: null, status: null,
    dirty: false, nameDirty: false, saving: false, uploading: false,
    tab: "transcript", refreshing: false, renderSignature: "",
    modelChosen: false, connected: false, toastTimer: null,
    pollTimer: null, playingSegment: null,
    trash: [], deleting: false, restoringId: null, deletedIds: new Set(),
    collectionVersion: 0, selectionRequest: 0, notesStarting: false, retrying: false,
    emptyingTrash: false, emptyTrashIds: [], trashLoading: 0, trashFeedback: "", trashLoadError: "",
    addSpeakerContext: null, removeSpeakerContext: null, draggedParagraph: null,
    searchQuery: "", searchResults: [], searchTotal: 0, searchHasMore: false, searchLoading: false,
    searchRequest: 0, searchTimer: null, searchError: "", searchOpening: false, pendingSearchResult: null,
    templatesLoaded: false, noteTemplates: [], templateSaving: false,
  };
  const fallbackTemplates = [
    { id: "meeting", name: "Meeting minutes", description: "A summary, decisions, action items, and open questions.", summary_heading: "Summary", sections: [{ key: "decisions", label: "Decisions" }, { key: "actions", label: "Action items", show_owner_due: true }, { key: "open_questions", label: "Open questions" }] },
    { id: "lecture", name: "Lecture notes", description: "A summary, key concepts, study tasks, and review questions.", summary_heading: "Summary", sections: [{ key: "decisions", label: "Key concepts" }, { key: "actions", label: "Study tasks", show_owner_due: true }, { key: "open_questions", label: "Review questions" }] },
    { id: "journal", name: "Journal", description: "A summary, highlights and reflections, follow-ups, and open questions.", summary_heading: "Summary", sections: [{ key: "decisions", label: "Highlights & reflections" }, { key: "actions", label: "Follow-ups", show_owner_due: true }, { key: "open_questions", label: "Open questions" }] },
  ];
  const activeStatuses = new Set(["queued", "processing", "running"]);
  const languageNames = { en: "English", es: "Spanish", pt: "Portuguese", auto: "Automatic language" };
  const fileInput = $("file-input");
  const audio = $("audio-player");

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }
  function show(element, visible = true) {
    element.classList.toggle("hidden", !visible);
  }
  function timestamp(value) {
    const seconds = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    return (hours ? String(hours) + ":" + String(minutes).padStart(2, "0") : String(minutes)) + ":" + String(seconds % 60).padStart(2, "0");
  }
  function durationLabel(value) {
    if (!value) return "";
    const minutes = Math.floor(Number(value) / 60);
    return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : minutes ? `${minutes} min` : `${Math.round(value)} sec`;
  }
  function dateLabel(value) {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function percent(value) {
    const numeric = Number(value) || 0;
    return Math.max(0, Math.min(100, numeric <= 1 ? numeric * 100 : numeric));
  }
  function errorText(error) {
    if (typeof error === "string") return error;
    if (Array.isArray(error)) return error.map((item) => item.msg || item.message || String(item)).join("; ");
    if (error && typeof error === "object") return error.message || JSON.stringify(error);
    return "Something went wrong. Please try again.";
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    let data;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
      const error = new Error(errorText(data && (data.detail || data.error || data.message)) || `Request failed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return data;
  }
  function toast(message, isError = false) {
    const box = $("toast");
    box.textContent = message;
    box.classList.toggle("error", isError);
    show(box);
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => show(box, false), isError ? 7000 : 4000);
  }
  function speakerList(job = state.job) {
    if (!job) return [];
    const speakers = Array.isArray(job.speakers) ? job.speakers.map((s) => typeof s === "string" ? { id: s, name: "" } : { ...s }) : Object.entries(job.speakers || {}).map(([id, name]) => ({ id, name }));
    for (const segment of job.segments || []) {
      if (segment.speaker != null && !speakers.some((speaker) => String(speaker.id) === String(segment.speaker))) speakers.push({ id: segment.speaker, name: "" });
    }
    return speakers.sort((a, b) => Number(isUnknownSpeaker(a)) - Number(isUnknownSpeaker(b)));
  }
  function isUnknownSpeaker(speaker) { return String(speaker.id).toUpperCase() === "UNKNOWN"; }
  function speakerIndex(id) {
    return Math.max(0, speakerList().findIndex((speaker) => String(speaker.id) === String(id)));
  }
  function speakerName(speaker, index) {
    return speaker.name && String(speaker.name).trim() || (isUnknownSpeaker(speaker) ? "Unassigned" : `Speaker ${index + 1}`);
  }
  function markDirty(names = false) {
    state.dirty = true;
    state.nameDirty = state.nameDirty || names;
    renderDirty();
  }
  function renderDirty() {
    show($("save-transcript"), state.dirty);
    show($("unsaved-hint"), state.dirty);
    show($("save-speakers"), state.nameDirty);
    $("save-transcript").disabled = state.saving || state.templateSaving;
    $("save-speakers").disabled = state.saving || state.templateSaving;
    $("save-transcript").textContent = state.saving ? "Saving…" : "Save changes";
    $("save-speakers").textContent = state.saving ? "Saving…" : "Save changes";
    $("unsaved-hint").textContent = state.job?.notes && state.job.notes_stale
      ? "You have unsaved changes. Save them, then regenerate meeting notes to reflect your latest edits."
      : "You have unsaved changes. Save them before generating notes or exporting.";
    updateRecordingActions();
  }
  function updateRecordingActions() {
    const busy = activeStatuses.has(state.job?.status) || activeStatuses.has(state.job?.notes_status) || state.notesStarting || state.retrying;
    const blocked = state.saving || state.templateSaving || state.uploading || state.deleting || Boolean(state.restoringId) || state.emptyingTrash;
    $("delete-recording").disabled = !state.job || busy || blocked;
    $("delete-recording").textContent = state.deleting ? "Moving to Trash…" : "Delete recording";
    $("delete-recording").title = busy ? "Wait for processing to finish before deleting this recording." : "Move to Trash. You can restore it later.";
    $("export-button").disabled = !state.job || state.job.status !== "complete" || state.deleting;
    $("new-recording").disabled = state.templateSaving || state.uploading || state.deleting || Boolean(state.restoringId) || state.emptyingTrash;
    $("notes-template").disabled = !state.job || blocked || busy;
    const editDisabled = !speakerEditsAllowed();
    $("use-one-speaker").disabled = editDisabled;
    $("add-speaker").disabled = editDisabled;
    for (const input of document.querySelectorAll("#recording-title, .speaker-select, .person-fields input, .edit-segment, .passage-toolbar button, .paragraph-remove-speaker, .remove-person, .paragraph-drag-handle")) input.disabled = editDisabled;
    for (const editor of document.querySelectorAll(".passage-editor")) {
      editor.contentEditable = String(!editDisabled);
      editor.setAttribute("aria-disabled", String(editDisabled));
    }
    for (const handle of document.querySelectorAll(".paragraph-drag-handle")) handle.draggable = false;
    updateTrashActions();
  }
  function renderStatus(status) {
    state.status = status;
    state.connected = true;
    if (Array.isArray(status.languages) && status.languages.length) {
      const select = $("language-select");
      const selected = select.value || "en";
      const languages = status.languages.filter((entry) => entry && typeof entry.code === "string" && typeof entry.name === "string");
      const signature = languages.map((entry) => `${entry.code}:${entry.name}`).join("|");
      if (select.dataset.catalog !== signature) {
        select.replaceChildren(...languages.map((entry) => {
          languageNames[entry.code] = entry.name;
          const option = node("option", "", entry.name); option.value = entry.code; return option;
        }));
        select.value = languages.some((entry) => entry.code === selected) ? selected : "en";
        select.dataset.catalog = signature;
      }
    }
    $("connection-dot").className = "status-dot";
    $("connection-text").textContent = "Local workspace";
    show($("notice"), false);
    const setup = status.setup || {};
    const ready = Boolean(status.ready || status.models && status.models.ready);
    const running = activeStatuses.has(setup.state);
    const failed = setup.state === "failed";
    show($("setup-banner"), !ready || running || failed);
    $("setup-title").textContent = running ? "Getting your listening room ready" : failed ? "The model download needs another try" : "Make room for every voice";
    $("setup-description").textContent = setup.error || (running ? setup.message || "Downloading the models. You only need to do this once." : "Download the transcription models once, then process recordings on your computer.");
    $("setup-button").disabled = running;
    $("setup-button").textContent = running ? "Setting up…" : failed ? "Retry setup" : "Set up transcription";
    show($("setup-progress"), running);
    $("setup-progress").value = percent(setup.progress);
    const ollama = status.ollama || {};
    const available = Boolean(ollama.available);
    $("ollama-dot").className = `status-dot ${available ? "" : "muted"}`;
    const models = Array.isArray(ollama.models) ? ollama.models.map((model) => typeof model === "string" ? model : model.name).filter(Boolean) : [];
    const select = $("model-select");
    const previous = state.modelChosen ? select.value : ollama.selected || select.value || "qwen3.5:9b";
    const options = models.length ? models : [previous];
    if (Array.from(select.options).map((option) => option.value).join("|") !== options.join("|")) {
      select.replaceChildren(...options.map((model) => {
        const option = node("option", "", model);
        option.value = model;
        return option;
      }));
    }
    if (options.includes(previous)) select.value = previous;
    $("ollama-hint").textContent = available && models.length ? "Ollama is connected. This model turns your transcript into meeting notes." : available ? "Ollama is running. Add a text model to create meeting notes." : "Start Ollama on this computer to create meeting notes. Transcription works independently.";
    updateNotesButton();
  }
  function renderLibrary() {
    $("library-count").textContent = String(state.jobs.length);
    const list = $("job-list");
    if (!state.jobs.length) {
      const empty = node("p", "library-empty", "A little space for\neverything worth keeping.");
      empty.style.whiteSpace = "pre-line";
      list.replaceChildren(empty);
      return;
    }
    list.replaceChildren(...state.jobs.map((job) => {
      const item = node("button", `job-item${job.id === state.selectedId ? " selected" : ""}`);
      item.type = "button";
      item.setAttribute("aria-current", job.id === state.selectedId ? "true" : "false");
      item.title = job.title || job.filename || "Untitled recording";
      item.append(node("span", "job-item-title", item.title));
      const meta = node("span", "job-item-meta");
      const labels = { queued: "In queue", processing: "Transcribing", running: "Transcribing", complete: "Ready", failed: "Needs attention" };
      meta.append(node("span", `job-item-status ${job.status || ""}`, labels[job.status] || job.status || "New"));
      meta.append(node("span", "", durationLabel(job.duration) || dateLabel(job.created_at)));
      item.append(meta);
      item.addEventListener("click", () => selectJob(job.id));
      return item;
    }));
  }
  async function selectJob(id, force = false) {
    if (state.deleting || state.restoringId || state.emptyingTrash || state.templateSaving || state.deletedIds.has(id)) return false;
    if (state.dirty && !force) {
      if (state.selectedId === id) return;
      toast("Save your changes before opening another recording.");
      $("save-transcript").focus();
      return;
    }
    const request = ++state.selectionRequest;
    const version = state.collectionVersion;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (request !== state.selectionRequest || version !== state.collectionVersion || state.deletedIds.has(id) || (state.dirty && !force)) return;
      state.selectedId = id;
      state.job = job;
      state.dirty = false;
      state.nameDirty = false;
      state.renderSignature = "";
      state.playingSegment = null;
      try { localStorage.setItem("meeting-studio-selected", id); } catch { /* Storage may be disabled. */ }
      renderLibrary();
      renderJob();
      return true;
    } catch (error) { if (request === state.selectionRequest && version === state.collectionVersion && !state.deletedIds.has(id)) toast(error.message, true); }
    return false;
  }
  function renderSearch() {
    const results = $("search-results");
    results.replaceChildren(...state.searchResults.map((result, index) => {
      const button = node("button", "search-result");
      button.type = "button"; button.id = `search-result-${index}`;
      button.disabled = state.searchOpening;
      button.append(node("strong", "search-result-title", result.title || result.filename || "Untitled recording"));
      button.append(node("span", "search-result-time", `Listen at ${timestamp(result.start)}`));
      const snippet = node("span", "search-result-snippet");
      const text = String(result.snippet || "");
      const start = Math.max(0, Math.min(text.length, Number(result.match_start) || 0));
      const end = Math.max(start, Math.min(text.length, Number(result.match_end) || 0));
      snippet.append(text.slice(0, start), node("mark", "", text.slice(start, end)), text.slice(end));
      button.append(snippet);
      button.addEventListener("click", () => requestSearchResult(result));
      return button;
    }));
    const message = state.searchError || (state.searchLoading ? (state.searchResults.length ? "Loading more matches…" : "Searching your transcripts…")
      : !state.searchQuery ? "Search completed recordings in your library."
        : !state.searchResults.length ? "No matching phrases found. Try a different word or phrase."
          : `${state.searchTotal} ${state.searchTotal === 1 ? "match" : "matches"} · ${state.searchResults.length} shown`);
    $("search-status").textContent = message;
    $("search-status").classList.toggle("error", Boolean(state.searchError));
    $("search-results").setAttribute("aria-busy", String(state.searchLoading || state.searchOpening));
    show($("search-more"), state.searchHasMore);
    $("search-more").disabled = state.searchLoading || state.searchOpening;
  }
  async function searchRecordings(append = false) {
    clearTimeout(state.searchTimer);
    const query = $("recording-search").value.trim();
    if (append && (state.searchLoading || query !== state.searchQuery)) return;
    const request = ++state.searchRequest;
    const version = state.collectionVersion;
    const offset = append ? state.searchResults.length : 0;
    state.searchQuery = query; state.searchError = "";
    if (!append) { state.searchResults = []; state.searchTotal = 0; state.searchHasMore = false; }
    state.searchLoading = Boolean(query);
    renderSearch();
    if (!query) return;
    try {
      const data = await api(`/api/search?q=${encodeURIComponent(query)}&limit=50&offset=${offset}`);
      if (request !== state.searchRequest || query !== $("recording-search").value.trim()) return;
      if (version !== state.collectionVersion) { state.searchLoading = false; searchRecordings(); return; }
      const results = Array.isArray(data.results) ? data.results : [];
      state.searchResults = append ? [...state.searchResults, ...results] : results;
      state.searchTotal = Number(data.total) || 0; state.searchHasMore = Boolean(data.has_more);
    } catch (error) {
      if (request !== state.searchRequest) return;
      state.searchError = `Search couldn’t finish. ${error.message} Try searching again.`;
    } finally {
      if (request === state.searchRequest) { state.searchLoading = false; renderSearch(); }
    }
  }
  function requestSearchResult(result) {
    if (state.searchOpening || state.saving || state.templateSaving || state.deleting || state.restoringId || state.emptyingTrash || state.uploading) return;
    collectVisibleEdits();
    if (state.dirty && state.selectedId !== result.job_id) {
      state.pendingSearchResult = result;
      show($("search-unsaved-error"), false);
      $("search-unsaved-dialog").showModal(); $("cancel-search-open").focus();
      return;
    }
    openSearchResult(result);
  }
  async function openSearchResult(result) {
    if (state.searchOpening) return;
    state.searchOpening = true; renderSearch();
    try {
      if (state.selectedId !== result.job_id && !await selectJob(result.job_id)) {
        state.searchError = "That recording could not be opened. It may have changed or moved to Trash. Search again to refresh the results.";
        return;
      }
      if (!state.job || state.job.id !== result.job_id) return;
      const segment = (state.job.segments || []).find((part) => String(part.id) === String(result.segment_id));
      if (!segment) { state.searchError = "This transcript changed. Search again to find the latest matches."; return; }
      $("search-dialog").close();
      jumpToSegment(segment);
    } finally { state.searchOpening = false; renderSearch(); }
  }
  function noteTemplate(id) {
    return state.noteTemplates.find((template) => template.id === id) || fallbackTemplates.find((template) => template.id === id) || fallbackTemplates[0];
  }
  function renderTemplatePicker() {
    const selected = noteTemplate(state.job?.notes_template || state.job?.notes?.template || "meeting");
    const select = $("notes-template");
    const templates = state.noteTemplates.length ? state.noteTemplates : fallbackTemplates;
    if (select.dataset.catalog !== JSON.stringify(templates)) {
      select.replaceChildren(...templates.map((template) => { const option = node("option", "", template.name); option.value = template.id; return option; }));
      select.dataset.catalog = JSON.stringify(templates);
    }
    select.value = selected.id;
    $("notes-template-description").textContent = state.templateSaving ? "Saving your notes format…" : selected.description;
  }
  async function changeNotesTemplate() {
    if (!state.job || state.saving || state.templateSaving) return;
    collectVisibleEdits();
    const job = state.job, previous = job.notes_template || job.notes?.template || "meeting";
    const selected = $("notes-template").value;
    if (selected === previous) return;
    state.templateSaving = true; ++state.selectionRequest; job.notes_template = selected;
    renderTemplatePicker(); renderDirty(); updateNotesButton();
    try {
      const saved = await api(`/api/jobs/${encodeURIComponent(job.id)}`, { method: "PATCH", body: JSON.stringify({ notes_template: selected }) });
      if (state.job?.id === job.id) {
        state.job.notes_template = saved.notes_template || selected;
        state.job.notes_stale = Boolean(saved.notes_stale || state.dirty && state.job.notes);
        state.renderSignature = "";
      }
    } catch (error) { if (state.job?.id === job.id) state.job.notes_template = previous; toast(error.message, true); }
    finally { ++state.selectionRequest; state.templateSaving = false; renderNotes(); renderDirty(); }
  }
  function clearSelectedJob() {
    ++state.selectionRequest;
    state.selectedId = null;
    state.job = null;
    state.dirty = false;
    state.nameDirty = false;
    state.renderSignature = "";
    state.playingSegment = null;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    try { localStorage.removeItem("meeting-studio-selected"); } catch { /* Storage may be disabled. */ }
    show($("export-menu"), false);
    $("export-button").setAttribute("aria-expanded", "false");
    renderLibrary();
    renderJob();
  }
  function renderTrash() {
    $("trash-count").textContent = String(state.trash.length);
    updateTrashActions();
    renderTrashMessage();
    const list = $("trash-list");
    if (!state.trash.length) {
      const empty = node("div", "trash-empty");
      empty.append(node("strong", "", "Trash is empty"), node("p", "", "Recordings you delete will appear here, ready to restore."));
      list.replaceChildren(empty);
      return;
    }
    list.replaceChildren(...state.trash.map((entry) => {
      const row = node("article", "trash-row");
      const copy = node("div", "trash-row-copy");
      copy.append(node("h3", "", entry.title || entry.filename || "Untitled recording"));
      copy.append(node("p", "", entry.purge_started ? "Deletion started — empty Trash again to finish." : [entry.deleted_at ? `Deleted ${dateLabel(entry.deleted_at)}` : "Deleted recording", durationLabel(entry.duration)].filter(Boolean).join(" · ")));
      const restore = node("button", "button button-secondary button-small", state.restoringId === entry.id ? "Restoring…" : "Restore");
      restore.id = `restore-${entry.id}`;
      restore.type = "button";
      restore.disabled = Boolean(entry.purge_started) || Boolean(state.restoringId) || state.deleting || state.uploading || state.emptyingTrash;
      restore.setAttribute("aria-label", `Restore ${entry.title || entry.filename || "recording"}`);
      restore.addEventListener("click", () => restoreRecording(entry.id));
      row.append(copy, restore);
      return row;
    }));
  }
  function updateTrashActions() {
    const mutating = state.deleting || Boolean(state.restoringId) || state.uploading || state.emptyingTrash;
    $("empty-trash").disabled = !state.trash.length || state.trashLoading > 0 || mutating || Boolean(state.trashLoadError);
    $("empty-trash").textContent = state.emptyingTrash ? "Emptying Trash…" : "Empty Trash";
    $("cancel-empty-trash").disabled = state.emptyingTrash;
    $("confirm-empty-trash").disabled = state.emptyingTrash || !state.emptyTrashIds.length || state.deleting || Boolean(state.restoringId) || state.uploading;
    if (state.emptyingTrash) $("confirm-empty-trash").textContent = "Deleting…";
  }
  function renderTrashMessage() {
    const message = state.trashLoadError || state.trashFeedback || (state.trashLoading > 0 ? "Loading Trash…" : "");
    $("trash-status").textContent = message;
    show($("trash-status"), Boolean(message));
  }
  function requestEmptyTrash() {
    if (!state.trash.length || state.trashLoading > 0 || state.deleting || state.restoringId || state.uploading || state.emptyingTrash || state.trashLoadError) return;
    const ids = [...new Set(state.trash.map((entry) => entry.id).filter((id) => /^[0-9a-f]{32}$/.test(id)))];
    if (!ids.length) return;
    state.emptyTrashIds = ids;
    const label = `${ids.length} ${ids.length === 1 ? "recording" : "recordings"}`;
    $("empty-trash-count").textContent = `Permanently delete ${label} from Trash?`;
    $("confirm-empty-trash").textContent = `Delete ${label}`;
    updateTrashActions();
    if (!$("empty-trash-dialog").open) $("empty-trash-dialog").showModal();
    $("cancel-empty-trash").focus();
  }
  async function emptyTrash() {
    if (state.emptyingTrash || !state.emptyTrashIds.length || !$("empty-trash-dialog").open || state.deleting || state.restoringId || state.uploading) return;
    const ids = [...state.emptyTrashIds];
    state.emptyingTrash = true;
    state.trashFeedback = "";
    state.trashLoadError = "";
    ++state.collectionVersion;
    ++state.selectionRequest;
    renderTrash();
    updateRecordingActions();
    try {
      const result = await api("/api/trash/empty", { method: "POST", body: JSON.stringify({ ids }) });
      if (!Array.isArray(result?.deleted_ids) || !Array.isArray(result?.failed_ids)) throw new Error("The app returned an incomplete result.");
      const deleted = new Set(result.deleted_ids.filter((id) => ids.includes(id)));
      const failed = ids.filter((id) => !deleted.has(id));
      state.trash = state.trash.filter((entry) => !deleted.has(entry.id));
      for (const id of deleted) state.deletedIds.add(id);
      for (const id of failed) state.deletedIds.delete(id);
      const removed = `${deleted.size} ${deleted.size === 1 ? "recording" : "recordings"}`;
      state.trashFeedback = failed.length
        ? `${deleted.size ? `Permanently deleted ${removed}.` : "No recordings were deleted."} ${failed.length} ${failed.length === 1 ? "recording could" : "recordings could"} not be deleted. It may have been restored or changed; review the updated list before trying again.`
        : `Permanently deleted ${removed}.`;
    } catch (error) {
      state.trashFeedback = `Empty Trash didn’t finish. ${error.message} Review the updated list before trying again.`;
    } finally {
      ++state.collectionVersion;
      ++state.selectionRequest;
    }
    try {
      const entries = await api("/api/trash");
      state.trash = Array.isArray(entries) ? entries : [];
      state.trashLoadError = "";
    } catch (error) {
      state.trashLoadError = `Couldn’t refresh Trash. ${error.message} Close and reopen Trash to check what remains.`;
    } finally {
      state.emptyingTrash = false;
      state.emptyTrashIds = [];
      $("empty-trash-dialog").close();
      renderTrash();
      updateRecordingActions();
      ($("empty-trash").disabled ? $("close-trash") : $("empty-trash")).focus();
      scheduleRefresh(0);
    }
  }
  async function loadTrash() {
    if (state.deleting || state.restoringId || state.emptyingTrash) return;
    const version = state.collectionVersion;
    ++state.trashLoading;
    updateTrashActions();
    renderTrashMessage();
    try {
      const entries = await api("/api/trash");
      if (version !== state.collectionVersion) return;
      state.trash = Array.isArray(entries) ? entries : [];
      state.trashLoadError = "";
      renderTrash();
    } catch (error) {
      if (version !== state.collectionVersion) return;
      state.trashLoadError = `Couldn’t load Trash. ${error.message}`;
    } finally {
      --state.trashLoading;
      updateTrashActions();
      renderTrashMessage();
    }
  }
  async function deleteRecording() {
    const job = state.job;
    if (!job || state.deleting || state.restoringId || state.saving || state.uploading || state.emptyingTrash) return;
    if (state.dirty) { toast("Save your changes before deleting this recording."); $("save-transcript").focus(); return; }
    if (activeStatuses.has(job.status) || activeStatuses.has(job.notes_status) || state.notesStarting || state.retrying) {
      toast("Wait for processing to finish before deleting this recording.");
      return;
    }
    state.deleting = true;
    ++state.collectionVersion;
    ++state.selectionRequest;
    state.deletedIds.add(job.id);
    renderDirty();
    updateNotesButton();
    let deleted = false;
    try {
      await api(`/api/jobs/${encodeURIComponent(job.id)}`, { method: "DELETE" });
      deleted = true;
      state.jobs = state.jobs.filter((entry) => entry.id !== job.id);
      state.trash = [{ id: job.id, title: job.title, filename: job.filename, created_at: job.created_at, duration: job.duration, deleted_at: new Date().toISOString() }, ...state.trash.filter((entry) => entry.id !== job.id)];
      clearSelectedJob();
      renderTrash();
      toast("Moved to Trash. You can restore it from the sidebar.");
    } catch (error) {
      state.deletedIds.delete(job.id);
      toast(error.message, true);
    } finally {
      state.deleting = false;
      renderDirty();
      updateNotesButton();
      renderTrash();
    }
    if (deleted && !state.selectedId && state.jobs.length) await selectJob(state.jobs[0].id);
    scheduleRefresh(0);
  }
  async function restoreRecording(id) {
    if (state.restoringId || state.deleting || state.uploading || state.emptyingTrash || state.trash.find((entry) => entry.id === id)?.purge_started) return;
    state.restoringId = id;
    ++state.collectionVersion;
    ++state.selectionRequest;
    renderTrash();
    updateRecordingActions();
    let restored = null;
    try {
      restored = await api(`/api/trash/${encodeURIComponent(id)}/restore`, { method: "POST" });
      state.deletedIds.delete(id);
      state.trash = state.trash.filter((entry) => entry.id !== id);
      state.jobs = [restored, ...state.jobs.filter((entry) => entry.id !== id)].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
      renderLibrary();
      toast("Recording restored to your library.");
    } catch (error) { toast(error.message, true); }
    finally {
      state.restoringId = null;
      renderTrash();
      updateRecordingActions();
    }
    if (restored && !state.selectedId && !state.dirty) await selectJob(restored.id);
    scheduleRefresh(0);
  }
  function renderJob() {
    const job = state.job;
    show($("welcome-view"), !job);
    show($("recording-view"), Boolean(job));
    if (!job) {
      $("transcript-list").replaceChildren();
      $("notes-content").replaceChildren();
      renderPeople();
      renderDirty();
      updateNotesButton();
      return;
    }
    const signature = JSON.stringify(job);
    if (signature === state.renderSignature) { updateRecordingActions(); return; }
    state.renderSignature = signature;
    if (document.activeElement !== $("recording-title")) $("recording-title").value = job.title || job.filename || "Untitled recording";
    $("recording-meta").textContent = [dateLabel(job.created_at), durationLabel(job.duration), languageNames[job.language] || job.language, job.filename].filter(Boolean).join(" · ");
    $("recording-eyebrow").textContent = job.status === "complete" ? "A CONVERSATION, KEPT" : "YOUR RECORDING";
    const audioUrl = `/api/jobs/${encodeURIComponent(job.id)}/audio`;
    if (audio.getAttribute("src") !== audioUrl) audio.src = audioUrl;
    const busy = activeStatuses.has(job.status);
    show($("job-progress-card"), busy);
    const stageLabels = { queued: "Waiting for its turn", loading: "Preparing the models", transcribing: "Listening to your recording", transcription: "Listening to your recording", diarizing: "Finding the voices", diarization: "Finding the voices", aligning: "Matching words to moments", alignment: "Matching words to moments", complete: "Ready to review" };
    $("job-stage").textContent = stageLabels[job.stage] || job.stage || (job.status === "queued" ? "Waiting for its turn" : "Listening to your recording");
    $("job-progress").value = percent(job.progress);
    $("job-percentage").textContent = `${Math.round(percent(job.progress))}%`;
    show($("job-error"), job.status === "failed");
    $("job-error-text").textContent = job.error || "This recording couldn’t be processed. Check setup and try again.";
    $("export-button").disabled = job.status !== "complete";
    for (const format of ["md", "docx", "json"]) $("export-" + format).href = `/api/jobs/${encodeURIComponent(job.id)}/export?format=${format}`;
    const segments = Array.isArray(job.segments) ? job.segments : [];
    $("segment-count").textContent = segments.length ? String(segments.length) : "";
    show($("segment-count"), Boolean(segments.length));
    renderTranscript(segments);
    renderPeople();
    renderNotes();
    renderDirty();
    setTab(state.tab);
  }
  function transcriptSegmentText(segment) {
    return passage.segmentDisplay(segment).text;
  }
  function speakerEditsAllowed() {
    return Boolean(state.job && state.job.status === "complete" && !state.saving && !state.templateSaving && !state.deleting && !state.restoringId && !state.uploading && !state.emptyingTrash);
  }
  function commitPassageEditor(editor) {
    if (!state.job || state.job.id !== editor.dataset.jobId || state.saving) return false;
    const runs = passage.readEditor(editor);
    const signature = JSON.stringify(runs);
    if (signature === editor.dataset.signature) return false;
    const ids = JSON.parse(editor.dataset.segmentIds);
    const segments = ids.map((id) => (state.job.segments || []).find((entry) => String(entry.id) === String(id)));
    if (segments.some((segment) => !segment)) return false;
    const edited = passage.applyEdit(segments, runs);
    edited.forEach((segment, index) => Object.assign(segments[index], { text: segment.text, text_join_before: segment.text_join_before, runs: segment.runs }));
    editor.dataset.signature = signature;
    state.job.notes_stale = Boolean(state.job.notes) || activeStatuses.has(state.job.notes_status);
    markDirty();
    updateNotesButton();
    return true;
  }
  function collectVisibleEdits() {
    if (!state.job) return;
    for (const editor of document.querySelectorAll(".passage-editor")) if (!editor.closest(".hidden")) commitPassageEditor(editor);
    for (const input of document.querySelectorAll(".person-fields input")) {
      const speaker = (state.job.speakers || []).find((entry) => String(entry.id) === input.dataset.speakerId);
      if (speaker && speaker.name !== input.value) { speaker.name = input.value; state.dirty = true; state.nameDirty = true; }
    }
  }
  function draftSpeakersChanged(names = false) {
    state.job.notes_stale = Boolean(state.job.notes) || activeStatuses.has(state.job.notes_status);
    markDirty(names);
    state.renderSignature = "";
    renderJob();
  }
  function speakerOptions(select, speakers, allowAdd = false) {
    for (const [index, speaker] of speakers.entries()) {
      const option = node("option", "", speakerName(speaker, index)); option.value = String(speaker.id); select.append(option);
    }
    if (!speakers.some(isUnknownSpeaker)) { const option = node("option", "", "Unassigned"); option.value = "UNKNOWN"; select.append(option); }
    if (allowAdd) { const option = node("option", "", "+ Add speaker…"); option.value = "__add_speaker__"; select.append(option); }
  }
  function ensureAssignmentTarget(id) {
    const speakers = speakerList();
    let target = speakers.find((entry) => String(entry.id) === String(id));
    if (!target && id === "UNKNOWN") { target = { id: "UNKNOWN", name: "Unassigned" }; speakers.push(target); }
    if (!target) return null;
    state.job.speakers = speakers;
    return target;
  }
  function assignTranscriptParts(ids, speakerId, jobId = state.job?.id) {
    if (!speakerEditsAllowed() || state.job.id !== jobId) return false;
    collectVisibleEdits();
    const target = ensureAssignmentTarget(speakerId);
    if (!target) { toast("That speaker is no longer in this recording. Choose another person."); return false; }
    const selected = new Set(ids.map(String));
    let changed = false;
    for (const segment of state.job.segments || []) if (selected.has(String(segment.id)) && segment.speaker !== target.id) { segment.speaker = target.id; changed = true; }
    if (changed) { draftSpeakersChanged(); toast(`Assigned to ${speakerName(target, speakerIndex(target.id))}. Save changes to keep it.`); }
    return changed;
  }
  function openAddSpeaker(ids = []) {
    if (!speakerEditsAllowed()) return;
    collectVisibleEdits();
    state.addSpeakerContext = { jobId: state.job.id, ids: [...ids] };
    $("new-speaker-name").value = "";
    $("speaker-add-description").textContent = ids.length ? "Add a person and assign this paragraph to them. Save your changes when you’re ready." : "Add someone to this recording. Your changes stay as a draft until you save.";
    show($("speaker-add-error"), false);
    $("speaker-add-dialog").showModal();
    $("new-speaker-name").focus();
  }
  function addSpeaker(name, ids = [], jobId = state.job?.id) {
    if (!speakerEditsAllowed() || state.job.id !== jobId || !String(name).trim()) return false;
    collectVisibleEdits();
    const speakers = speakerList();
    let id;
    do { id = `SPEAKER_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`; } while (speakers.some((entry) => entry.id === id));
    speakers.push({ id, name: String(name).trim().slice(0, 100) });
    state.job.speakers = speakers;
    const selected = new Set(ids.map(String));
    for (const segment of state.job.segments || []) if (selected.has(String(segment.id))) segment.speaker = id;
    draftSpeakersChanged(true);
    return id;
  }
  function openRemoveSpeaker(id) {
    if (!speakerEditsAllowed()) return;
    collectVisibleEdits();
    const speakers = speakerList();
    const speaker = speakers.find((entry) => String(entry.id) === String(id));
    if (!speaker || isUnknownSpeaker(speaker)) return;
    state.removeSpeakerContext = { jobId: state.job.id, id: speaker.id };
    const count = (state.job.segments || []).filter((entry) => entry.speaker === speaker.id).length;
    $("speaker-remove-description").textContent = `Remove ${speakerName(speaker, speakers.indexOf(speaker))} from this entire recording and reassign their ${count} transcript ${count === 1 ? "part" : "parts"}. Words, timing, and conversation order stay the same.`;
    const select = $("remove-speaker-replacement"); select.replaceChildren();
    speakerOptions(select, speakers.filter((entry) => entry.id !== speaker.id)); select.value = "UNKNOWN";
    show($("speaker-remove-error"), false);
    $("speaker-remove-dialog").showModal(); $("cancel-remove-speaker").focus();
  }
  function removeSpeaker(id, replacementId, jobId = state.job?.id) {
    if (!speakerEditsAllowed() || state.job.id !== jobId || id === replacementId) return false;
    collectVisibleEdits();
    const source = speakerList().find((entry) => entry.id === id);
    if (!source || isUnknownSpeaker(source) || !ensureAssignmentTarget(replacementId)) return false;
    for (const segment of state.job.segments || []) if (segment.speaker === id) segment.speaker = replacementId;
    state.job.speakers = state.job.speakers.filter((entry) => entry.id !== id);
    draftSpeakersChanged(true);
    return true;
  }
  function groupTranscriptSegments(segments) {
    const groups = [];
    for (const segment of segments) {
      const previous = groups[groups.length - 1];
      const display = passage.segmentDisplay(segment);
      const textLength = Array.from(display.text).length;
      const joinLength = Array.from(display.joinBefore).length;
      const lastSegment = previous?.segments[previous.segments.length - 1];
      const startsParagraph = !previous || String(previous.speaker) !== String(segment.speaker)
        || Number(segment.start) - Number(lastSegment.end) >= 8
        || (segment.text_join_before !== "" && previous.textLength + joinLength + textLength > 900);
      if (startsParagraph) groups.push({ speaker: segment.speaker, segments: [segment], textLength });
      else {
        previous.segments.push(segment);
        previous.textLength += joinLength + textLength;
      }
    }
    return groups;
  }
  function renderTranscript(segments) {
    const list = $("transcript-list");
    if (!segments.length) {
      const box = node("div", "transcript-empty");
      box.append(node("strong", "", state.job.status === "complete" ? "A quiet recording." : "Every word will find its place."));
      box.append(node("span", "", state.job.status === "complete" ? "No speech was found in this recording." : "Your transcript and speaker groups will appear here when processing is finished."));
      list.replaceChildren(box);
      return;
    }
    const speakers = speakerList();
    const timeButton = (segment) => {
      const time = node("button", "timestamp", timestamp(segment.start));
      time.type = "button";
      time.title = `Listen from ${timestamp(segment.start)}`;
      time.setAttribute("aria-label", time.title);
      time.addEventListener("click", () => seek(segment.start));
      return time;
    };
    list.replaceChildren(...groupTranscriptSegments(segments).map((group) => {
      const first = group.segments[0];
      const jobId = state.job.id;
      const segmentIds = group.segments.map((segment) => segment.id);
      const item = node("article", "segment transcript-group");
      const top = node("div", "segment-top paragraph-top");
      const speakerIdx = speakerIndex(group.speaker);
      const speaker = speakers.find((entry) => String(entry.id) === String(group.speaker));
      const assignment = node("div", "paragraph-assignment");
      const assignLabel = node("label", "", "Assign speaker");
      const assign = node("select", `speaker-select paragraph-speaker-select speaker-color-${speakerIdx % 5}`);
      assign.id = `paragraph-speaker-${first.id}`; assignLabel.htmlFor = assign.id;
      assign.setAttribute("aria-label", `Assign speaker for paragraph at ${timestamp(first.start)}`);
      speakerOptions(assign, speakers, true); assign.value = String(group.speaker ?? "UNKNOWN");
      assign.addEventListener("change", () => {
        if (assign.value === "__add_speaker__") { assign.value = String(group.speaker ?? "UNKNOWN"); openAddSpeaker(segmentIds); }
        else assignTranscriptParts(segmentIds, assign.value, jobId);
      });
      assignment.append(assignLabel, assign);
      const drag = node("button", "paragraph-drag-handle", "⠿");
      drag.type = "button"; drag.draggable = false; drag.id = `drag-paragraph-${first.id}`;
      drag.setAttribute("aria-label", `Drag paragraph at ${timestamp(first.start)} onto a person to assign its speaker`);
      drag.title = "Drag onto a person to assign this paragraph. You can also use Assign speaker.";
      let pointerDrag = null;
      const targetAtPointer = (event) => document.elementFromPoint(event.clientX, event.clientY)?.closest(".person-row");
      const clearPointerDrag = (event) => {
        try { if (drag.hasPointerCapture(event.pointerId)) drag.releasePointerCapture(event.pointerId); } catch { /* The handle may have been redrawn. */ }
        pointerDrag = null; state.draggedParagraph = null; item.classList.remove("dragging");
        for (const row of document.querySelectorAll(".person-row")) row.classList.remove("drop-target");
      };
      drag.addEventListener("pointerdown", (event) => {
        if (event.button !== 0 || !speakerEditsAllowed() || state.job.id !== jobId) return;
        event.preventDefault();
        collectVisibleEdits();
        pointerDrag = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
        state.draggedParagraph = { jobId, segmentIds };
        drag.setPointerCapture(event.pointerId);
      });
      drag.addEventListener("pointermove", (event) => {
        if (!pointerDrag || pointerDrag.id !== event.pointerId) return;
        event.preventDefault();
        if (Math.hypot(event.clientX - pointerDrag.x, event.clientY - pointerDrag.y) >= 6) pointerDrag.moved = true;
        if (!pointerDrag.moved) return;
        item.classList.add("dragging");
        const target = targetAtPointer(event);
        for (const row of document.querySelectorAll(".person-row")) row.classList.toggle("drop-target", row === target && speakerEditsAllowed());
      });
      drag.addEventListener("pointerup", (event) => {
        if (!pointerDrag || pointerDrag.id !== event.pointerId) return;
        event.preventDefault();
        const target = pointerDrag.moved ? targetAtPointer(event) : null;
        clearPointerDrag(event);
        if (target?.dataset.speakerId) assignTranscriptParts(segmentIds, target.dataset.speakerId, jobId);
        else if (!target) assign.focus();
      });
      drag.addEventListener("pointercancel", clearPointerDrag);
      drag.addEventListener("lostpointercapture", () => {
        if (pointerDrag) { pointerDrag = null; state.draggedParagraph = null; item.classList.remove("dragging"); for (const row of document.querySelectorAll(".person-row")) row.classList.remove("drop-target"); }
      });
      drag.addEventListener("click", () => assign.focus());
      const actions = node("div", "paragraph-actions");
      if (speaker && !isUnknownSpeaker(speaker)) {
        const remove = node("button", "paragraph-remove-speaker", "Remove speaker…");
        remove.type = "button"; remove.title = "Remove this speaker from the entire recording and reassign their transcript";
        remove.setAttribute("aria-label", `Remove ${speakerName(speaker, speakerIdx)} from the entire recording`);
        remove.addEventListener("click", () => openRemoveSpeaker(group.speaker)); actions.append(remove);
      }
      const edit = node("button", "edit-segment", "Edit passage");
      edit.type = "button";
      edit.setAttribute("aria-label", `Edit passage at ${timestamp(first.start)}`);
      edit.setAttribute("aria-expanded", "false");
      const text = node("p", "segment-text");
      const details = node("div", "segment-details hidden");
      details.id = `paragraph-editor-${first.id}`;
      edit.setAttribute("aria-controls", details.id);
      const initial = passage.fromSegments(group.segments);
      const editor = node("div", "passage-editor");
      editor.id = `passage-editor-${first.id}`;
      editor.contentEditable = "true";
      editor.setAttribute("role", "textbox");
      editor.setAttribute("aria-multiline", "true");
      editor.setAttribute("aria-label", `Passage text at ${timestamp(first.start)}`);
      editor.dataset.jobId = jobId;
      editor.dataset.segmentIds = JSON.stringify(segmentIds);
      passage.renderRuns(editor, initial.runs);
      editor.dataset.signature = JSON.stringify(passage.readEditor(editor));
      const toolbar = node("div", "passage-toolbar");
      toolbar.setAttribute("role", "toolbar");
      toolbar.setAttribute("aria-label", `Format passage at ${timestamp(first.start)}`);
      for (const [command, label, visible] of [["bold", "Bold", "B"], ["italic", "Italic", "I"], ["underline", "Underline", "U"], ["undo", "Undo", "↶"], ["redo", "Redo", "↷"]]) {
        const button = node("button", `passage-format passage-${command}`, visible);
        button.id = `passage-${command}-${first.id}`;
        button.type = "button"; button.title = label;
        button.setAttribute("aria-label", `${label} in passage at ${timestamp(first.start)}`);
        button.addEventListener("mousedown", (event) => event.preventDefault());
        button.addEventListener("click", () => {
          if (!speakerEditsAllowed()) return;
          editor.focus();
          document.execCommand("styleWithCSS", false, false);
          document.execCommand(command, false);
          commitPassageEditor(editor);
        });
        toolbar.append(button);
      }
      editor.addEventListener("input", () => commitPassageEditor(editor));
      editor.addEventListener("paste", (event) => {
        event.preventDefault();
        if (!speakerEditsAllowed()) return;
        const pasted = (event.clipboardData?.getData("text/plain") || "").replace(/\r\n?/g, "\n");
        document.execCommand("insertText", false, pasted);
        commitPassageEditor(editor);
      });
      editor.addEventListener("drop", (event) => event.preventDefault());
      details.append(toolbar, editor, node("p", "field-hint segment-edit-hint", "Edit the whole passage. Formatting and line breaks are saved with your transcript."));
      const endEdit = () => {
        collectVisibleEdits();
        renderTranscript(state.job?.segments || []);
        renderDirty();
      };
      group.segments.forEach((segment, index) => {
        const display = passage.segmentDisplay(segment);
        const fragment = node("span", "transcript-fragment");
        fragment.dataset.segmentId = String(segment.id);
        passage.renderRuns(fragment, display.runs);
        if (index) text.append(display.joinBefore);
        text.append(fragment);
      });
      if (!initial.text.trim()) text.append(node("span", "empty-passage", "Empty passage"));
      editor.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); endEdit(); } });
      edit.addEventListener("click", () => {
        const opening = details.classList.contains("hidden");
        if (!opening) { endEdit(); return; }
        show(details); show(text, false); edit.textContent = "Done";
        edit.setAttribute("aria-expanded", "true");
        editor.focus();
      });
      actions.append(edit);
      top.append(drag, timeButton(first), assignment, actions);
      item.append(top, text, details);
      return item;
    }));
  }
  function renderPeople() {
    const speakers = speakerList();
    if (state.job) state.job.speakers = speakers;
    const assignedCount = speakers.filter((speaker) => !isUnknownSpeaker(speaker)).length;
    $("people-count").textContent = assignedCount ? String(assignedCount) : "—";
    show($("speaker-review-hint"), Boolean(speakers.length));
    const canConsolidate = state.job?.status === "complete" && speakers.length > 1 && Boolean(state.job.segments?.length);
    show($("use-one-speaker"), canConsolidate);
    show($("use-one-speaker-hint"), canConsolidate);
    const list = $("people-list");
    if (!speakers.length) {
      const empty = node("div", "people-empty");
      empty.append(node("span", "person-outline", "♧"));
      empty.append(node("p", "", "Voices will appear here after transcription."));
      list.replaceChildren(empty);
      return;
    }
    list.replaceChildren(...speakers.map((speaker, index) => {
      const row = node("div", "person-row");
      row.id = `speaker-card-${speaker.id}`;
      row.dataset.speakerId = String(speaker.id);
      row.setAttribute("role", "group");
      row.setAttribute("aria-label", `${speakerName(speaker, index)}. Drop a paragraph here to assign its speaker.`);
      row.addEventListener("dragover", (event) => {
        if (!speakerEditsAllowed() || !state.draggedParagraph || state.draggedParagraph.jobId !== state.job.id) return;
        event.preventDefault(); event.dataTransfer.dropEffect = "move"; row.classList.add("drop-target");
      });
      row.addEventListener("dragleave", (event) => { if (!row.contains(event.relatedTarget)) row.classList.remove("drop-target"); });
      row.addEventListener("drop", (event) => {
        event.preventDefault(); row.classList.remove("drop-target");
        if (!speakerEditsAllowed()) return;
        let payload = state.draggedParagraph;
        try { payload = JSON.parse(event.dataTransfer.getData("application/x-meeting-studio-paragraph")) || payload; } catch { /* Only an app paragraph can be assigned. */ }
        if (!payload || payload.jobId !== state.job.id || !Array.isArray(payload.segmentIds)) return;
        state.draggedParagraph = null;
        assignTranscriptParts(payload.segmentIds, speaker.id, payload.jobId);
      });
      const avatar = node("span", `avatar color-${index % 5}`, speaker.name ? String(speaker.name).trim().charAt(0).toUpperCase() : isUnknownSpeaker(speaker) ? "?" : String(index + 1));
      const fields = node("div", "person-fields");
      const label = node("label", "", isUnknownSpeaker(speaker) ? "UNASSIGNED" : `SPEAKER ${index + 1}`);
      const input = node("input");
      input.type = "text";
      input.id = `person-name-${index}`;
      input.dataset.speakerId = String(speaker.id);
      input.maxLength = 100;
      input.value = speaker.name || "";
      input.placeholder = isUnknownSpeaker(speaker) ? "Unassigned" : "Add a name";
      label.htmlFor = input.id;
      input.addEventListener("input", () => {
        const liveSpeaker = (state.job?.speakers || []).find((entry) => String(entry.id) === String(speaker.id));
        if (!liveSpeaker) return;
        liveSpeaker.name = input.value;
        speaker.name = input.value;
        avatar.textContent = input.value.trim().charAt(0).toUpperCase() || (isUnknownSpeaker(speaker) ? "?" : String(index + 1));
        for (const select of document.querySelectorAll(".speaker-select")) {
          for (const option of select.options) if (option.value === String(speaker.id)) option.textContent = speakerName(speaker, index);
        }
        for (const label of document.querySelectorAll(".speaker-label")) {
          if (label.dataset.speakerId === String(speaker.id)) label.textContent = speakerName(speaker, index);
        }
        markDirty(true);
      });
      input.addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); saveChanges(); } });
      fields.append(label, input);
      row.append(avatar, fields);
      if (!isUnknownSpeaker(speaker)) {
        const remove = node("button", "remove-person", "×");
        remove.type = "button"; remove.id = `remove-person-${speaker.id}`;
        remove.setAttribute("aria-label", `Remove ${speakerName(speaker, index)} from this recording`);
        remove.title = "Remove speaker and reassign their transcript";
        remove.addEventListener("click", () => openRemoveSpeaker(speaker.id)); row.append(remove);
      }
      return row;
    }));
  }
  function useOneSpeaker() {
    const job = state.job;
    if (!speakerEditsAllowed() || !(job.segments || []).length) return;
    collectVisibleEdits();
    const speakers = speakerList(job);
    if (speakers.length < 2) return;
    const first = speakers.find((speaker) => !isUnknownSpeaker(speaker)) || speakers[0];
    job.speakers = [{ ...first }];
    for (const segment of job.segments) segment.speaker = first.id;
    job.notes_stale = Boolean(job.notes) || activeStatuses.has(job.notes_status);
    markDirty(true);
    state.renderSignature = "";
    renderJob();
    toast(`Every line now uses ${speakerName(first, 0)}. Review and save your changes.`);
  }
  async function saveChanges() {
    collectVisibleEdits();
    if (!state.job || !state.dirty || state.saving || state.templateSaving) return;
    state.saving = true;
    renderDirty();
    try {
      const speakers = speakerList().map((speaker, index) => ({ id: speaker.id, name: String(speaker.name || "").trim() || speakerName({ ...speaker, name: "" }, index) }));
      const payload = { title: String(state.job.title || "").trim() || state.job.filename || "Untitled recording", speakers, segments: state.job.segments || [], notes_template: state.job.notes_template || state.job.notes?.template || "meeting" };
      const saved = await api(`/api/jobs/${encodeURIComponent(state.job.id)}`, { method: "PATCH", body: JSON.stringify(payload) });
      state.dirty = false;
      state.nameDirty = false;
      if (saved && saved.id) state.job = saved;
      else state.job = await api(`/api/jobs/${encodeURIComponent(state.job.id)}`);
      state.renderSignature = "";
      const entry = state.jobs.find((job) => job.id === state.job.id);
      if (entry) Object.assign(entry, { title: state.job.title });
      renderLibrary();
      renderJob();
      toast("Your changes are saved.");
    } catch (error) { toast(error.message, true); }
    finally { state.saving = false; renderDirty(); }
  }
  function updateNotesButton() {
    const button = $("generate-notes");
    const job = state.job;
    const busy = job && activeStatuses.has(job.notes_status);
    button.disabled = !job || job.status !== "complete" || !(job.segments || []).some((segment) => String(segment.text || "").trim()) || busy || state.notesStarting || state.saving || state.templateSaving || state.deleting || !state.status?.ollama?.available;
    button.textContent = state.notesStarting ? "Starting your notes…" : busy ? "Writing your notes…" : job && job.notes ? "Regenerate notes ✧" : "Generate notes ✧";
    button.title = !state.status?.ollama?.available ? "Start Ollama to generate meeting notes" : "Generate a draft from this transcript";
  }
  function renderNotes() {
    const job = state.job;
    if (!job) return;
    renderTemplatePicker();
    updateNotesButton();
    const selectedTemplate = noteTemplate(job.notes_template || job.notes?.template || "meeting");
    const generatedTemplate = noteTemplate(job.notes?.template || "meeting");
    const templateChanged = Boolean(job.notes && selectedTemplate.id !== generatedTemplate.id);
    $("notes-heading").textContent = job.notes ? generatedTemplate.name : selectedTemplate.name;
    const status = job.notes_status;
    const busy = activeStatuses.has(status);
    const failed = status === "failed";
    const statusBox = $("notes-state");
    show(statusBox, busy || failed || Boolean(job.notes_stale) || templateChanged);
    statusBox.classList.toggle("error", failed);
    statusBox.textContent = failed ? job.notes_error || "The notes couldn’t be generated. Check that your Ollama model is available, then try again." : busy ? job.notes_stage || "Your local assistant is reading the transcript and drafting your notes. You can keep listening while it works." : templateChanged ? `Showing your existing ${generatedTemplate.name.toLowerCase()}. Regenerate notes to use ${selectedTemplate.name.toLowerCase()}.` : "The transcript or speaker names have changed. Regenerate these notes to include your latest edits.";
    const content = $("notes-content");
    if (!job.notes) {
      const empty = node("div", "notes-empty");
      empty.append(node("span", "", "✧"), node("h3", "", "Keep the parts that matter."), node("p", "", `${selectedTemplate.description} Review your transcript, then generate a draft. The full transcript stays with your notes.`));
      content.replaceChildren(empty);
      return;
    }
    const notes = job.notes;
    const sections = [];
    const overview = node("section", "note-section");
    overview.append(node("h3", "", generatedTemplate.summary_heading || "Summary"), node("p", "", notes.overview || "No summary was generated."));
    sections.push(overview);
    for (const { key, label: title, show_owner_due } of generatedTemplate.sections) {
      const section = node("section", "note-section");
      section.append(node("h3", "", title));
      const items = Array.isArray(notes[key]) ? notes[key] : [];
      if (!items.length) section.append(node("p", "note-empty", "No entries were identified in this section."));
      else {
        const list = node("ul", "note-list");
        items.forEach((value) => {
          const entry = typeof value === "string" ? { text: value } : value;
          const item = node("li", "note-item");
          item.append(node("p", "", entry.text || ""));
          if (show_owner_due && (entry.owner || entry.due)) {
            const meta = node("div", "note-item-meta");
            if (entry.owner) meta.append(node("span", "", `Owner: ${entry.owner}`));
            if (entry.due) meta.append(node("span", "", `Due: ${entry.due}`));
            item.append(meta);
          }
          if (Array.isArray(entry.segment_ids) && entry.segment_ids.length) {
            const sources = node("div", "source-links");
            const seen = new Set();
            entry.segment_ids.forEach((id) => {
              const segment = (job.segments || []).find((seg) => String(seg.id) === String(id));
              if (!segment || seen.has(String(id))) return;
              seen.add(String(id));
              const button = node("button", "", `↗ ${timestamp(segment.start)}`);
              button.type = "button";
              button.title = `See source at ${timestamp(segment.start)}`;
              button.addEventListener("click", () => jumpToSegment(segment));
              sources.append(button);
            });
            if (sources.childElementCount) item.append(sources);
          }
          list.append(item);
        });
        section.append(list);
      }
      sections.push(section);
    }
    const transcript = node("details", "notes-full-transcript");
    transcript.append(node("summary", "", "Full transcript"));
    for (const group of groupTranscriptSegments(job.segments || [])) {
      const first = group.segments[0];
      const block = node("section", "notes-transcript-passage");
      const person = speakerList().find((speaker) => String(speaker.id) === String(group.speaker));
      const source = node("button", "timestamp", `${timestamp(first.start)} · ${person ? speakerName(person, speakerIndex(person.id)) : "Unassigned"}`);
      source.type = "button"; source.addEventListener("click", () => jumpToSegment(first));
      const content = node("p", "segment-text");
      const rich = passage.fromSegments(group.segments);
      passage.renderRuns(content, rich.runs);
      if (!rich.text.trim()) content.append(node("span", "empty-passage", "Empty passage"));
      block.append(source, content); transcript.append(block);
    }
    sections.push(transcript);
    content.replaceChildren(...sections);
  }
  function setTab(tab) {
    state.tab = tab;
    if (tab === "notes") renderNotes();
    for (const name of ["transcript", "notes"]) {
      const active = name === tab;
      $("tab-" + name).classList.toggle("active", active);
      $("tab-" + name).setAttribute("aria-selected", String(active));
      $("tab-" + name).tabIndex = active ? 0 : -1;
      show($(name + "-panel"), active);
    }
  }
  async function seek(seconds) {
    audio.currentTime = Math.max(0, Number(seconds) || 0);
    try { await audio.play(); } catch { /* Browser can require a second playback gesture. */ }
  }
  function jumpToSegment(segment) {
    setTab("transcript");
    seek(segment.start);
    const item = Array.from(document.querySelectorAll(".transcript-fragment")).find((element) => element.dataset.segmentId === String(segment.id) && !element.closest(".hidden"))
      || Array.from(document.querySelectorAll(".passage-editor")).find((element) => !element.closest(".hidden") && JSON.parse(element.dataset.segmentIds).some((id) => String(id) === String(segment.id)));
    if (!item) return;
    if (item.classList.contains("passage-editor")) item.focus({ preventScroll: true });
    item.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    item.classList.remove("highlighted");
    void item.offsetWidth;
    item.classList.add("highlighted");
  }
  async function uploadFiles(files) {
    if (!files || !files.length || state.templateSaving || state.uploading || state.deleting || state.restoringId || state.emptyingTrash) return;
    if (state.dirty) { toast("Save your current changes before adding a new recording."); return; }
    state.uploading = true;
    updateRecordingActions();
    document.body.classList.add("uploading");
    const button = $("new-recording");
    const original = button.textContent;
    button.textContent = "Adding recordings…";
    button.disabled = true;
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    form.append("language", $("language-select").value);
    if ($("speaker-count").value) form.append("num_speakers", $("speaker-count").value);
    try {
      const result = await api("/api/jobs", { method: "POST", body: form });
      const jobs = result.jobs || (Array.isArray(result) ? result : []);
      if (!jobs.length) throw new Error("No recordings were added. Please try again.");
      const listed = await api("/api/jobs");
      state.jobs = Array.isArray(listed) ? listed : listed.jobs || [];
      await selectJob(jobs[0].id, true);
      toast(`${jobs.length === 1 ? "Your recording is" : `${jobs.length} recordings are`} in the queue.`);
      renderLibrary();
    } catch (error) { toast(error.message, true); }
    finally {
      state.uploading = false;
      document.body.classList.remove("uploading");
      button.textContent = original;
      button.disabled = false;
      updateRecordingActions();
      fileInput.value = "";
      scheduleRefresh(1000);
    }
  }
  async function generateNotes() {
    if (!state.job || state.deleting || state.notesStarting || state.templateSaving) return;
    if (state.dirty) { toast("Save your transcript and speaker names before generating notes."); return; }
    const button = $("generate-notes");
    const id = state.job.id;
    state.notesStarting = true;
    updateRecordingActions();
    button.disabled = true;
    button.textContent = "Starting your notes…";
    try {
      const result = await api(`/api/jobs/${encodeURIComponent(id)}/notes`, { method: "POST", body: JSON.stringify({ model: $("model-select").value, template: $("notes-template").value }) });
      if (state.selectedId === id && !state.deletedIds.has(id)) {
        if (result && result.id) state.job = result;
        else state.job.notes_status = "queued";
        state.renderSignature = "";
        renderJob();
      }
      scheduleRefresh(1000);
    } catch (error) { toast(error.message, true); }
    finally { state.notesStarting = false; updateNotesButton(); updateRecordingActions(); }
  }
  function scheduleRefresh(delay) {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(refresh, delay);
  }
  async function refresh() {
    if (state.refreshing) return;
    if (state.deleting || state.restoringId || state.emptyingTrash) { scheduleRefresh(1000); return; }
    state.refreshing = true;
    ++state.trashLoading;
    updateTrashActions();
    const version = state.collectionVersion;
    try {
      const [statusResult, jobsResult, trashResult, templatesResult] = await Promise.allSettled([api("/api/status"), api("/api/jobs"), api("/api/trash"), state.templatesLoaded ? Promise.resolve(null) : api("/api/note-templates")]);
      if (version !== state.collectionVersion) return;
      if (statusResult.status === "fulfilled") renderStatus(statusResult.value);
      else throw statusResult.reason;
      if (templatesResult.status === "fulfilled" && Array.isArray(templatesResult.value?.templates)) {
        state.noteTemplates = templatesResult.value.templates.filter((template) => template && typeof template.id === "string" && Array.isArray(template.sections));
        state.templatesLoaded = Boolean(state.noteTemplates.length);
        if (state.job) renderNotes();
      }
      if (jobsResult.status === "fulfilled") {
        const jobs = Array.isArray(jobsResult.value) ? jobsResult.value : jobsResult.value.jobs || [];
        state.jobs = jobs.filter((job) => !state.deletedIds.has(job.id));
        renderLibrary();
      } else throw jobsResult.reason;
      if (trashResult.status === "fulfilled") {
        state.trash = Array.isArray(trashResult.value) ? trashResult.value : [];
        state.trashLoadError = "";
        renderTrash();
      } else {
        state.trashLoadError = `Couldn’t load Trash. ${trashResult.reason.message}`;
        renderTrashMessage();
      }
      if (state.selectedId && !state.jobs.some((job) => job.id === state.selectedId) && !state.dirty && !state.saving && !state.uploading) clearSelectedJob();
      if (state.selectedId) {
        if (!state.dirty && !state.saving && !state.templateSaving && !state.uploading) {
          const selectedId = state.selectedId;
          const selection = state.selectionRequest;
          const job = await api(`/api/jobs/${encodeURIComponent(selectedId)}`);
          if (version === state.collectionVersion && selection === state.selectionRequest && selectedId === state.selectedId && !state.deletedIds.has(selectedId) && !state.dirty && !state.saving && !state.templateSaving) {
            state.job = job;
            renderJob();
          }
        }
      } else if (state.jobs.length) {
        let savedId;
        try { savedId = localStorage.getItem("meeting-studio-selected"); } catch { /* Storage may be disabled. */ }
        await selectJob(state.jobs.some((job) => job.id === savedId) ? savedId : state.jobs[0].id);
      }
    } catch (error) {
      if (version !== state.collectionVersion) return;
      state.connected = false;
      $("connection-dot").className = "status-dot warning";
      $("connection-text").textContent = "Reconnecting";
      $("notice").textContent = "The local app isn’t responding yet. Keep its launcher open; this page will reconnect automatically.";
      show($("notice"));
    } finally {
      state.refreshing = false;
      --state.trashLoading;
      updateTrashActions();
      renderTrashMessage();
      const busy = state.uploading || state.jobs.some((job) => activeStatuses.has(job.status)) || activeStatuses.has(state.job?.notes_status) || activeStatuses.has(state.status?.setup?.state);
      scheduleRefresh(busy || !state.connected ? 2000 : 8000);
    }
  }

  $("new-recording").addEventListener("click", () => fileInput.click());
  $("open-search").addEventListener("click", () => {
    collectVisibleEdits();
    $("search-dialog").showModal(); $("recording-search").focus();
    searchRecordings();
  });
  $("close-search").addEventListener("click", () => $("search-dialog").close());
  $("search-dialog").addEventListener("close", () => { clearTimeout(state.searchTimer); ++state.searchRequest; state.searchLoading = false; });
  $("recording-search").addEventListener("input", () => {
    clearTimeout(state.searchTimer); ++state.searchRequest;
    state.searchQuery = $("recording-search").value.trim(); state.searchResults = []; state.searchTotal = 0; state.searchHasMore = false;
    state.searchError = ""; state.searchLoading = Boolean(state.searchQuery); renderSearch();
    state.searchTimer = setTimeout(() => searchRecordings(), 280);
  });
  $("search-form").addEventListener("submit", (event) => { event.preventDefault(); searchRecordings(); });
  $("search-more").addEventListener("click", () => searchRecordings(true));
  $("cancel-search-open").addEventListener("click", () => { if (!state.saving) $("search-unsaved-dialog").close(); });
  $("search-unsaved-dialog").addEventListener("cancel", (event) => { if (state.saving) event.preventDefault(); });
  $("search-unsaved-dialog").addEventListener("close", () => { state.pendingSearchResult = null; });
  $("save-search-open").addEventListener("click", async () => {
    const result = state.pendingSearchResult;
    if (!result || state.saving || state.templateSaving) return;
    $("save-search-open").disabled = true; $("cancel-search-open").disabled = true;
    $("save-search-open").textContent = "Saving…";
    try {
      await saveChanges();
      if (state.dirty) { $("search-unsaved-error").textContent = "Your changes could not be saved. Cancel to review them and try again."; show($("search-unsaved-error")); return; }
      $("search-unsaved-dialog").close();
      await openSearchResult(result);
    } finally { $("save-search-open").disabled = false; $("cancel-search-open").disabled = false; $("save-search-open").textContent = "Save and open"; }
  });
  $("notes-template").addEventListener("change", changeNotesTemplate);
  fileInput.addEventListener("change", () => uploadFiles(fileInput.files));
  const drop = $("drop-zone");
  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); } });
  ["dragenter", "dragover"].forEach((eventName) => drop.addEventListener(eventName, (event) => { event.preventDefault(); drop.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((eventName) => drop.addEventListener(eventName, (event) => { event.preventDefault(); drop.classList.remove("dragover"); }));
  drop.addEventListener("drop", (event) => uploadFiles(event.dataTransfer.files));
  window.addEventListener("dragover", (event) => { if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault(); });
  window.addEventListener("drop", (event) => { if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault(); });
  $("setup-button").addEventListener("click", async () => {
    const button = $("setup-button");
    button.disabled = true;
    button.textContent = "Starting setup…";
    try { await api("/api/setup", { method: "POST" }); await refresh(); }
    catch (error) { toast(error.message, true); button.disabled = false; button.textContent = "Retry setup"; }
  });
  $("recording-title").addEventListener("input", (event) => {
    if (!state.job) return;
    state.job.title = event.target.value;
    markDirty();
  });
  $("save-transcript").addEventListener("click", saveChanges);
  $("save-speakers").addEventListener("click", saveChanges);
  $("delete-recording").addEventListener("click", deleteRecording);
  $("open-trash").addEventListener("click", () => {
    renderTrash();
    if (!$("trash-dialog").open) $("trash-dialog").showModal();
    loadTrash();
  });
  $("close-trash").addEventListener("click", () => $("trash-dialog").close());
  $("empty-trash").addEventListener("click", requestEmptyTrash);
  $("confirm-empty-trash").addEventListener("click", emptyTrash);
  $("cancel-empty-trash").addEventListener("click", () => {
    if (!state.emptyingTrash) $("empty-trash-dialog").close();
  });
  $("empty-trash-dialog").addEventListener("cancel", (event) => {
    if (state.emptyingTrash) event.preventDefault();
  });
  $("empty-trash-dialog").addEventListener("close", () => {
    if (!state.emptyingTrash) { state.emptyTrashIds = []; updateTrashActions(); }
  });
  $("use-one-speaker").addEventListener("click", useOneSpeaker);
  $("add-speaker").addEventListener("click", () => openAddSpeaker());
  $("cancel-add-speaker").addEventListener("click", () => $("speaker-add-dialog").close());
  $("cancel-remove-speaker").addEventListener("click", () => $("speaker-remove-dialog").close());
  $("speaker-add-dialog").addEventListener("close", () => { state.addSpeakerContext = null; });
  $("speaker-remove-dialog").addEventListener("close", () => { state.removeSpeakerContext = null; });
  $("confirm-add-speaker").addEventListener("click", () => {
    const context = state.addSpeakerContext;
    const name = $("new-speaker-name").value.trim();
    if (!name) { $("speaker-add-error").textContent = "Enter a name for the new speaker."; show($("speaker-add-error")); $("new-speaker-name").focus(); return; }
    if (!context || !addSpeaker(name, context.ids, context.jobId)) {
      $("speaker-add-error").textContent = "This recording is no longer ready to edit. Close this window and try again."; show($("speaker-add-error")); return;
    }
    $("speaker-add-dialog").close();
    toast(`${name} was added. Save your changes when you’re ready.`);
  });
  $("new-speaker-name").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); $("confirm-add-speaker").click(); } });
  $("confirm-remove-speaker").addEventListener("click", () => {
    const context = state.removeSpeakerContext;
    if (!context || !removeSpeaker(context.id, $("remove-speaker-replacement").value, context.jobId)) {
      $("speaker-remove-error").textContent = "Choose another person or Unassigned. If this recording changed, close this window and try again."; show($("speaker-remove-error")); return;
    }
    $("speaker-remove-dialog").close();
    toast("Speaker removed and transcript reassigned. Save your changes to keep them.");
  });
  $("tab-transcript").addEventListener("click", () => setTab("transcript"));
  $("tab-notes").addEventListener("click", () => setTab("notes"));
  for (const name of ["transcript", "notes"]) $("tab-" + name).addEventListener("keydown", (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      setTab(event.key === "Home" ? "transcript" : event.key === "End" ? "notes" : name === "transcript" ? "notes" : "transcript");
      $("tab-" + state.tab).focus();
    }
  });
  $("generate-notes").addEventListener("click", generateNotes);
  $("retry-job").addEventListener("click", async () => {
    if (!state.job || state.deleting || state.retrying) return;
    if (state.dirty) { toast("Save your changes before retrying this recording."); return; }
    const button = $("retry-job");
    const id = state.job.id;
    state.retrying = true;
    updateRecordingActions();
    button.disabled = true;
    button.textContent = "Restarting…";
    try {
      const result = await api(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" });
      if (state.selectedId === id && !state.deletedIds.has(id)) {
        if (result && result.id) state.job = result;
        else state.job = await api(`/api/jobs/${encodeURIComponent(id)}`);
        state.renderSignature = "";
        renderJob();
      }
      scheduleRefresh(500);
      toast("Your recording is back in the queue.");
    } catch (error) { toast(error.message, true); }
    finally { state.retrying = false; button.disabled = false; button.textContent = "Retry recording"; updateRecordingActions(); }
  });
  $("model-select").addEventListener("change", () => { state.modelChosen = true; });
  $("export-button").addEventListener("click", () => {
    if (state.dirty) { toast("Save your changes before exporting."); return; }
    const opening = $("export-menu").classList.contains("hidden");
    show($("export-menu"), opening);
    $("export-button").setAttribute("aria-expanded", String(opening));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".export-wrap")) { show($("export-menu"), false); $("export-button").setAttribute("aria-expanded", "false"); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { show($("export-menu"), false); $("export-button").setAttribute("aria-expanded", "false"); }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s" && state.job) { event.preventDefault(); saveChanges(); }
  });
  for (const format of ["md", "docx", "json"]) $("export-" + format).addEventListener("click", (event) => {
    if (state.dirty) { event.preventDefault(); toast("Save your changes before exporting."); }
    show($("export-menu"), false);
    $("export-button").setAttribute("aria-expanded", "false");
  });
  audio.addEventListener("timeupdate", () => {
    if (!state.job) return;
    const current = (state.job.segments || []).find((segment) => audio.currentTime >= segment.start && audio.currentTime < segment.end);
    const id = current ? String(current.id) : null;
    if (id === state.playingSegment) return;
    state.playingSegment = id;
    for (const item of document.querySelectorAll(".transcript-fragment, .segment-editor-row")) item.classList.toggle("playing", item.dataset.segmentId === id);
  });
  audio.addEventListener("error", () => { if (state.job && audio.error) toast("This audio could not be played in the browser. Transcription can still process supported recording formats.", true); });
  window.addEventListener("beforeunload", (event) => { if (state.dirty) { event.preventDefault(); event.returnValue = ""; } });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) scheduleRefresh(0); });
  refresh();
})();
