"""Literal transcript search with original segment references and JS-safe offsets.

Formatting runs are presentation only. Legacy segments use the same trim-and-space
display rule as the transcript editor. Search folds case and whitespace while its
snippets and source references retain the original text, including rich-text joins.
"""
from bisect import bisect_right


def _transcript(segments):
    pieces, starts, sources = [], [], []
    length = 0
    for index, segment in enumerate(segments):
        raw = str(segment.get("text") or "")
        marker = segment.get("text_join_before")
        explicit = marker in ("", " ")
        text = raw if explicit else raw.strip()
        join = (marker if explicit else " ") if index else ""
        piece = join + text
        if piece:
            starts.append(length)
            sources.append(segment)
            pieces.append(piece)
            length += len(piece)
    return "".join(pieces), starts, sources


def _casefold_with_positions(text):
    folded, positions, ends = [], [], []
    previous_whitespace = False
    for index, char in enumerate(text):
        whitespace = char.isspace()
        if whitespace and previous_whitespace:
            ends[-1] = index + 1
            continue
        value = " " if whitespace else char.casefold()
        folded.append(value)
        positions.extend([index] * len(value))
        ends.extend([index + 1] * len(value))
        previous_whitespace = whitespace
    return "".join(folded), positions, ends


def _utf16_length(text):
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def search_recordings(recordings, query, limit=50, offset=0):
    """Search an immutable caller-owned snapshot, newest recording first.

match_start/match_end are UTF-16 indices into snippet, suitable for JS slice().
The result timestamp is the start of the original segment containing the match.
"""
    needle, _, _ = _casefold_with_positions(query)
    results, total = [], 0
    if not needle or not query.strip():
        return {"query": query, "results": results, "total": 0, "has_more": False}
    for job in sorted(recordings, key=lambda item: (item.get("created_at", ""), item["id"]), reverse=True):
        if job.get("deleted_at") or job.get("status") != "complete":
            continue
        text, starts, sources = _transcript(job.get("segments", []))
        folded, positions, ends = _casefold_with_positions(text)
        cursor = 0
        while True:
            found = folded.find(needle, cursor)
            if found < 0:
                break
            end = found + len(needle)
            cursor = end
            # Do not match only half of a case-fold expansion (for example ß -> ss).
            if (found and positions[found - 1] == positions[found]) or (end < len(positions) and positions[end - 1] == positions[end]):
                continue
            match_start, match_end = positions[found], ends[end - 1]
            if offset <= total < offset + limit:
                source = sources[bisect_right(starts, match_start) - 1]
                left, right = max(0, match_start - 85), min(len(text), match_end + 85)
                prefix = "…" if left else ""
                snippet = prefix + text[left:right] + ("…" if right < len(text) else "")
                highlight_start = _utf16_length(prefix + text[left:match_start])
                highlight_end = highlight_start + _utf16_length(text[match_start:match_end])
                results.append({"job_id": job["id"], "title": job.get("title", "Recording"),
                                "filename": job.get("filename", ""), "segment_id": source["id"],
                                "start": source["start"], "snippet": snippet,
                                "match_start": highlight_start, "match_end": highlight_end})
            total += 1
    return {"query": query, "results": results, "total": total, "has_more": offset + len(results) < total}
