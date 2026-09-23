"""Transcript search API checks with only synthetic isolated recordings."""
from copy import deepcopy
import json

import pytest
from test_speaker_assignment import assignment_api


@pytest.fixture
def search_api(assignment_api, monkeypatch):
    server, client = assignment_api
    monkeypatch.setattr(server, "jobs", {})
    def add(number, texts, **changes):
        segments = [{"id": 10 + index * 7, "start": index * 6.25, "end": index * 6.25 + 4,
                     "speaker": "SPEAKER_00", "text": text} for index, text in enumerate(texts)]
        job = {"id": f"{number:032x}", "title": f"Recording {number}", "filename": f"audio-{number}.wav",
               "created_at": f"2026-09-{number:02d}T12:00:00Z", "status": "complete", "segments": segments,
               "speakers": [{"id": "SPEAKER_00", "name": "Alex"}], "notes": None, **changes}
        server.jobs[job["id"]] = deepcopy(job)
        server.save_job(job)
        return job
    return server, client, add


def highlighted(result):
    raw = result["snippet"].encode("utf-16-le")
    return raw[result["match_start"] * 2:result["match_end"] * 2].decode("utf-16-le")


def test_trimmed_phrase_crosses_original_segments_and_returns_first_source(search_api):
    server, client, add = search_api
    job = add(1, ["The budget", "decision is final."])
    before = deepcopy(server.jobs)
    metadata = server.JOBS_DIR / job["id"] / "job.json"
    disk_before = metadata.read_bytes()
    response = client.get("/api/search", params={"q": "  BUDGET decision  "})
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "BUDGET decision"
    assert data["total"] == 1 and data["has_more"] is False
    result = data["results"][0]
    assert (result["job_id"], result["segment_id"], result["start"]) == (job["id"], 10, 0)
    assert highlighted(result) == "budget decision"
    assert server.jobs == before and metadata.read_bytes() == disk_before


def test_rich_join_empty_and_newline_whitespace_keep_exact_snippet(search_api):
    server, client, add = search_api
    job = add(1, ["😀 The bud", "get\n\n\tdecision is final."])
    for segment in server.jobs[job["id"]]["segments"]:
        segment["text_join_before"] = ""
        segment["runs"] = [{"text": segment["text"], "bold": True}]
    response = client.get("/api/search", params={"q": "budget   decision"})
    result = response.json()["results"][0]
    assert highlighted(result) == "budget\n\n\tdecision"
    assert result["match_start"] == len("😀 The ".encode("utf-16-le")) // 2
    assert result["snippet"] == "😀 The budget\n\n\tdecision is final."
    assert result["segment_id"] == 10


def test_unicode_casefold_and_regex_punctuation_are_literal(search_api):
    _, client, add = search_api
    add(1, ["😀 Straße costs $5.00 (A+B)?", "STRASSE again. aZZb"])
    matches = client.get("/api/search", params={"q": "strasse"}).json()
    assert matches["total"] == 2
    assert [highlighted(row) for row in matches["results"]] == ["Straße", "STRASSE"]
    literal = client.get("/api/search", params={"q": "$5.00 (A+B)?"}).json()
    assert literal["total"] == 1
    assert highlighted(literal["results"][0]) == "$5.00 (A+B)?"
    assert client.get("/api/search", params={"q": "a.*b"}).json()["total"] == 0


def test_only_active_completed_transcripts_are_searched(search_api):
    _, client, add = search_api
    active = add(1, ["search target"])
    add(2, ["search target"], deleted_at="2026-10-01T12:00:00Z")
    add(3, ["search target"], status="processing")
    add(4, ["search target"], status="failed")
    add(5, ["unrelated"], title="search target", notes={"overview": "search target"})
    data = client.get("/api/search", params={"q": "search target"}).json()
    assert data["total"] == 1
    assert [result["job_id"] for result in data["results"]] == [active["id"]]


def test_pagination_is_deterministic_and_timestamp_tracks_later_segment(search_api):
    _, client, add = search_api
    older = add(1, ["hit first", "hit second"])
    newer = add(2, ["unrelated", "hit third and hit fourth"])
    all_results = client.get("/api/search", params={"q": "hit"}).json()
    first = client.get("/api/search", params={"q": "hit", "limit": 2}).json()
    second = client.get("/api/search", params={"q": "hit", "limit": 2, "offset": 2}).json()
    assert all_results["total"] == first["total"] == second["total"] == 4
    assert first["has_more"] is True and second["has_more"] is False
    assert first["results"] + second["results"] == all_results["results"]
    assert [r["job_id"] for r in all_results["results"]] == [newer["id"], newer["id"], older["id"], older["id"]]
    assert first["results"][0]["segment_id"] == 17 and first["results"][0]["start"] == 6.25
    assert client.get("/api/search", params={"q": "hit", "offset": 99}).json()["results"] == []


@pytest.mark.parametrize("params", [{"q": ""}, {"q": " \n\t "}, {"q": "x" * 201},
                                    {"q": "hit", "limit": 0}, {"q": "hit", "limit": 101},
                                    {"q": "hit", "offset": -1}])
def test_invalid_search_is_rejected(search_api, params):
    _, client, _ = search_api
    assert client.get("/api/search", params=params).status_code in (400, 422)


def test_snippet_truncation_keeps_utf16_offsets_and_query_text(search_api):
    _, client, add = search_api
    add(1, ["🙂" * 100 + "find this" + "x" * 200])
    result = client.get("/api/search", params={"q": "find this"}).json()["results"][0]
    assert result["snippet"].startswith("…") and result["snippet"].endswith("…")
    assert highlighted(result) == "find this"
