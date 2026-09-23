"""Built-in note purposes, presentation labels, and grounded generation prompts."""
from copy import deepcopy

DEFAULT_TEMPLATE = "meeting"

_TEMPLATES = {
    "meeting": {
        "id": "meeting", "name": "Meeting minutes", "description": "Decisions, agreed actions, and unresolved questions.",
        "summary_heading": "Summary",
        "sections": [{"key": "decisions", "label": "Decisions", "show_owner_due": False},
                     {"key": "actions", "label": "Action items", "show_owner_due": True},
                     {"key": "open_questions", "label": "Open questions", "show_owner_due": False}],
    },
    "lecture": {
        "id": "lecture", "name": "Lecture notes", "description": "Key concepts, stated study tasks, and questions to review.",
        "summary_heading": "Summary",
        "sections": [{"key": "decisions", "label": "Key concepts", "show_owner_due": False},
                     {"key": "actions", "label": "Study tasks", "show_owner_due": False},
                     {"key": "open_questions", "label": "Review questions", "show_owner_due": False}],
    },
    "journal": {
        "id": "journal", "name": "Journal", "description": "Spoken reflections, intended follow-ups, and open questions.",
        "summary_heading": "Summary",
        "sections": [{"key": "decisions", "label": "Highlights & reflections", "show_owner_due": False},
                     {"key": "actions", "label": "Follow-ups", "show_owner_due": False},
                     {"key": "open_questions", "label": "Open questions", "show_owner_due": False}],
    },
}
TEMPLATE_IDS = frozenset(_TEMPLATES)

_PROMPTS = {
    "meeting": """Purpose: meeting notes. In overview, summarize what the participants discussed.
Use decisions for decisions actually made, not proposals. Use actions for explicitly
agreed tasks, with the stated owner and due date only. Use open_questions for unresolved
questions raised in the meeting. Do not turn possibilities into commitments.""",
    "lecture": """Purpose: lecture or study notes. In overview, summarize the lesson's subject.
Use decisions for key concepts, definitions, explanations, and examples actually taught;
this field means Key concepts here, not meeting decisions. Use actions only for study
tasks or assignments explicitly stated in the recording, not exercises you invent.
Use open_questions for review questions actually posed or unresolved issues identified
by the speaker. Do not invent quiz questions, external explanations, or extra facts.""",
    "journal": """Purpose: personal journal notes. In overview, summarize the speaker's account.
Use decisions for highlights, events, and reflections the speaker actually expressed;
this field means Highlights & reflections here, not meeting decisions. Use actions only
for follow-ups the speaker explicitly intends or commits to. Use open_questions for
questions or uncertainties the speaker voiced. Do not infer emotions, motives, diagnoses,
personality, mental health, or psychological meaning. Do not give advice or invent tasks.""",
}


def get_template(template_id=DEFAULT_TEMPLATE):
    """Return independent display metadata; unknown legacy values use Meeting."""
    return deepcopy(_TEMPLATES.get(template_id, _TEMPLATES[DEFAULT_TEMPLATE]))


def list_templates():
    return [get_template(template_id) for template_id in _TEMPLATES]


def template_prompt(template_id=DEFAULT_TEMPLATE):
    if template_id not in TEMPLATE_IDS:
        raise ValueError("Choose Meeting, Lecture, or Journal notes.")
    return _PROMPTS[template_id]
