# Meeting Studio

**Your recordings. Your model. Your computer.**

A Windows app for turning recordings into searchable, speaker-labelled transcripts and structured notes for meetings, lectures or a journal. Whisper transcribes audio, local speaker models group voices, and your chosen Ollama model drafts notes. After setup, the complete workflow runs offline.

## Download and start

This preview supports **Windows 10/11 on x64 computers**. Mac, Linux, and ARM-native installers are not included.

1. Download the **Windows-x64.zip** from the [latest release](https://github.com/Peterdt99/meeting-studio/releases/latest) and **extract the entire folder** into a writable location, such as Documents. Do not run it inside the ZIP or place it in Program Files.
2. Double-click **Install.cmd**. It checks for 64-bit Python 3.12 and can offer to install it through Windows Package Manager. It then prepares the app and downloads its audio models.
3. Setup opens the app. Use **Start.cmd**, **Meeting Studio.exe**, or the shortcut on subsequent visits.
4. For meeting notes, install [Ollama](https://ollama.com/download) separately and download a local text model. For example, run **ollama pull qwen3.5:9b** in Terminal. Select it under **Your notes assistant**. Transcription and speaker editing work without Ollama.

The first setup needs internet and may take several minutes. Audio models occupy about 535 MB; Python libraries and Ollama models need additional space. Model choice and available memory affect performance. A dedicated GPU is not required for the included speech pipeline.

The desktop window also requires Microsoft's **WebView2 Runtime** and **.NET Framework 4.8**. The window checks for WebView2 when starting. **Start.cmd -Browser** opens the browser interface as a fallback. Keep the executable, icon, and companion DLLs together. This preview is not code signed.

Run **Install shortcuts.cmd** to create desktop and Start menu shortcuts. To pin the app, open it, right-click its taskbar icon, and select **Pin to taskbar**. Closing the window leaves transcription and note generation running locally.

## Your workflow

1. Copy recordings from your recorder, phone, or computer. Import one recording or a batch.
2. Choose the recording language before importing. English is the default; automatic detection is available.
3. Leave **Detect speakers automatically** selected for conversations, or choose a known count. **1 speaker — just me** keeps speech together and skips voice splitting.
4. Listen, correct the text, and assign names to the voices.
5. Choose a notes template, then generate and review its summary, sections and transcript references.
6. Export Word, Markdown, or JSON, including the full transcript and speaker names.

MP3, WAV, M4A, FLAC, OGG, AAC, WMA, AIFF, OPUS, WebM, MP4, and 3GP imports are accepted. Batches support up to 30 files, with a 2 GB limit per file. Work is processed one recording at a time.

## Find a passage

Choose **Search recordings** to find words or a phrase across completed transcripts in your library. Results show the recording, matching text and timestamp. Open a result to return to that passage; choose **Load more** for additional matches. Recordings in Trash are excluded.

Search stays on this computer and does not use an AI model. If you have unsaved changes, you can save them before opening a result or cancel to keep editing.

## Choose a notes template

Use the notes template picker before generating notes:

| Template | Sections after the summary |
| --- | --- |
| Meeting minutes | Decisions, Action items, Open questions |
| Lecture notes | Key concepts, Study tasks, Review questions |
| Journal | Highlights & reflections, Follow-ups, Open questions |

All templates use the recording as their source and include timestamp references. Review the draft for accuracy. Meeting action items show an owner and due date when stated; the other templates omit those fields.

Changing the template selects the format for the next generation. Existing notes keep the headings of the template that produced them until you regenerate them. Older notes without a template are treated as Meeting minutes. Word and Markdown exports follow the saved notes template, with the summary first, its sections next and the full transcript afterward.

## Assign transcript parts to people

Every paragraph has an **Assign speaker** menu. Choose a person, **Unassigned**, or add a new speaker directly from that menu. You can also drag a paragraph's handle onto a person under **People in the room**.

Use **Edit passage** to correct the whole passage in one text field. Select words and use **Bold**, **Italic**, or **Underline**; line breaks and formatting are retained when you save and export. **Add speaker** adds a person. **Remove speaker** lets you choose where all of that person's transcript parts should go; it does not remove their words.

Changes remain drafts until you choose **Save changes**. Wording, timestamps, and conversation order are preserved when changing speakers. Consecutive sentences assigned to one person regroup into paragraphs, with breaks for a speaker change, a pause of eight seconds, or a long paragraph. A passage you edit stays together even if you make it longer. Passage edits retain the original source identifiers and timestamps for note references. Saved edits mark existing notes as needing an update. Word exports keep native text formatting; Markdown uses inline HTML tags for bold, italic, and underline around escaped text.

Names apply within each recording. The app does not identify people across separate meetings.

## Languages

Choose from **99 languages supported by the installed multilingual Whisper small model**, including English, Spanish, Portuguese, Russian, and Chinese (Mandarin), or use automatic detection. All are included in the same model; no separate language packs are needed.

Accuracy varies by language, accent, noise, and microphone quality. Supported does not mean equally accurate. Automatic detection selects a primary language per recording. Cantonese is not a selectable language in this model. The interface remains in English; selecting a recording language does not request translation.

The selected Ollama model's language abilities separately affect meeting notes. Speaker grouping can also make mistakes, especially with overlapping speech or similar voices.

Sources: [multilingual Whisper small](https://huggingface.co/Systran/faster-whisper-small), [Whisper model card](https://github.com/openai/whisper/blob/main/model-card.md).

## Delete recordings and empty Trash

Choose **Delete recording** beside Export. Save edits first; transcription and notes must finish before deletion.

Deleted recordings move to **Trash**, where **Restore** recovers their audio, transcript, names, and notes. Trash has no automatic expiry.

To reclaim disk space, choose **Empty Trash** and confirm the displayed count. This permanently removes those recordings and their saved audio, transcripts, names, and notes. It cannot be undone. Original files outside the app, separately saved exports, downloaded models, and recordings still in the library are unaffected.

If Windows locks a file, unfinished deletion stays in Trash for a retry. Once permanent removal has started, that recording cannot be restored.

## Privacy and storage

- Audio and reviewed work are in **data/recordings**. Back up **data** to retain your work.
- Speech models are in **data/models**. Browser profiles and local diagnostic logs also live under **data**.
- The app listens only on this computer at **http://127.0.0.1:8766**. It is not a network or cloud service.
- Ollama is contacted at **127.0.0.1:11434**; the app rejects cloud models.
- Processing has no analytics, external fonts, or cloud uploads.
- After initial downloads, transcription, editing, voice grouping, notes, and exports can work in airplane mode.

Keep the app folder in place after installation. If moved, rerun setup and recreate shortcuts. Do not publish a working app directory wholesale: use the release packaging script to exclude recordings, models, logs, caches, and machine-specific runtime settings.

## Troubleshooting

- **Python missing:** follow Install.cmd's Python 3.12 instructions. Other Python versions are not currently tested.
- **Models missing or download interrupted:** rerun setup. Completed downloads are reused.
- **Ollama unavailable:** start Ollama and install a local text model. Transcription still works independently.
- **Too many speaker labels:** choose a known count before importing, or correct an existing recording using Assign speaker.
- **Processing interrupted:** use Retry on a failed recording or import the original again.
- **Blank taskbar icon after updating:** close and reopen the desktop app and run Install shortcuts.cmd. If Windows still displays a cached icon, unpin the old entry and pin the updated app.
- **App cannot open:** try Start.cmd -Browser and inspect data/server-errors.log. Check that port 8766 is not occupied by another program.
- **Stop the backend:** when no work is processing, end its Python process in Task Manager. No startup service is installed.

## Development and sharing

The service uses FastAPI, faster-whisper, sherpa-onnx, and python-docx. The interface uses HTML/CSS/JavaScript. The Windows wrapper uses WinForms and WebView2; source and build instructions are under **desktop**.

Run the synthetic Python and passage editor tests described in **tests/README.md** before sharing changes. Development checks use Python 3.12 and Node.js 24; Node.js is not required to use the app.

See **RELEASE_CHECKLIST.md** for preparing a clean GitHub release. Build the wrapper with **desktop/Build.ps1**. Publishing a repository or GitHub release is a separate step; setup does not publish anything.

This preview was tested on the development Windows computer and through isolated API/browser checks. A clean GitHub Windows runner also passed prerequisite checks, installed the Python libraries, compiled the desktop wrapper and ran the 1.1.1 Python and JavaScript regression suites. Full interactive setup and model downloads on a fresh PC, and audio accuracy in all 99 languages, have not been individually verified. Automatic speaker counts remain estimates. Word exports passed content and document-structure checks; visually review documents before sharing.

## License

Original Meeting Studio application code is **MIT licensed**; see **LICENSE**. Models, dependencies, and Microsoft components retain their own terms; see **THIRD_PARTY_NOTICES.md**, **licenses**, and the WebView2 license/notice files. Ollama models are downloaded separately under their respective licenses.
