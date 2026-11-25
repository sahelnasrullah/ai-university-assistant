# AI University Assistant

Personal side project. It is separate from the Generative AI course project
(that one is a simple RAG system and lives in `~/Documents/bth/gen_ai`).

## Idea in one sentence

A personal university assistant. The student links their account once and then
just asks questions. The assistant looks everything up and answers without the
student having to open Canvas, the schedule or the course pages.

## How we got here (project history)

1. **Starting point: a domain-specific RAG assistant.**
   We picked "domain-specific RAG assistant" from the list of suggested topics
   (RAG, LoRA fine-tuning, agentic AI, multimodal). A Q&A assistant over
   university documents was the safest and easiest to evaluate.

2. **Extension: connect it to the student's own Canvas data.**
   Instead of static documents only, the assistant should use the student's
   real data, for example: "When is Assignment 2 in Generative AI due?" or
   "When is my next lesson?"

3. **Realisation: that part is not RAG.**
   Looking up a due date or a calendar entry through an API is **tool calling
   (agentic AI)**. The model calls a function and reads structured JSON.
   Nothing is embedded, indexed or retrieved by similarity. Calling it RAG
   would be technically wrong. Embedding-based retrieval is also unreliable
   for exact dates and "what is next" questions.

4. **Decision: hybrid system.**
   - **Agentic tool calling** for structured, live data (deadlines, calendar,
     grades, course lists).
   - **RAG** for unstructured text (syllabi, lecture slides, announcements,
     regulations, course descriptions).
   - Proposed title direction: "An Agentic University Assistant with RAG for
     Canvas and Course Information". Final title to be decided.

5. **Scope direction:** everything the student would otherwise look up by hand
   (see the question list below).

## What the assistant should answer

| Question type | Example | Likely mechanism |
|---|---|---|
| Next lecture | "When is my next lecture?" | Tool call: schedule / calendar |
| Preparation | "What do I need to prepare for it?" | RAG over course plan, module pages, announcements + tool call to find which lecture |
| Lecture content | "What is the lecture about?" | RAG over course plan, slides, module pages |
| Grades | "What grade did I get on the exam?" | Tool call: Canvas grades API (or Ladok, see risks) |
| Future courses | "Which courses am I reading next semester?" | Tool call and/or RAG over the programme plan (see risks) |
| Deadlines | "When is my next assignment due?" / "When is Assignment 2 in Generative AI due?" | Tool call: Canvas assignments API |
| Course policies | "What are the grading rules for this course?" | RAG over syllabus and regulations |

## Planned data sources

- **Canvas REST API** (Instructure): courses, assignments with `due_at`,
  calendar events, announcements, modules, files, grades. Official API, so no
  HTML scraping. Needs a personal access token or OAuth.
- **Schedule:** BTH probably uses TimeEdit, which offers iCal export.
  **Not verified yet.**
- **Public BTH documents:** course syllabi, programme plans, study
  regulations (bth.se).
- **Test data:** an anonymised or mock Canvas dataset so the work can be
  reproduced without exposing real student data.

## Design ideas so far

- Read-only. The assistant never changes anything in Canvas.
- Start simple: the user pastes an API token once. Full OAuth login is optional.
- Run a quantised open LLM locally (for example via Ollama) so personal data
  does not leave the machine.
- Keep the scope small: start with 2-3 courses, then grow.

## Evaluation ideas

- Question set with ground truth taken from the API.
- Exact-match accuracy on dates, times and grades.
- Correct tool selection rate.
- RAGAS faithfulness and answer relevance on the document questions.
- Baseline comparison: plain RAG only versus RAG + tools on date and schedule
  questions.

## Open questions and risks

- Can BTH students create Canvas access tokens? Which BTH Canvas URL?
- **Grades:** Canvas shows grades only if teachers use it. Official results at
  Swedish universities usually live in Ladok, which probably has no easy
  student API. Unverified.
- **Next-semester courses:** probably not in Canvas. May need the programme
  plan from bth.se (RAG) or a student-provided document.
- **Schedule:** confirm TimeEdit iCal export and whether it is stable.
- **Privacy / GDPR:** tokens and personal data must stay local.
- **Scope creep:** the list of questions is already large. Decide the core set
  for the first working version.

## Next steps

1. Confirm the open questions above (token access, TimeEdit, grades source).
2. Pick the core question set for a first working version.
3. Build the tool-calling layer first (deadlines, schedule), then add RAG over
   course documents.

## Candidate sources (links collected, status checked on 2026-11-25)

| Source | What it is | Status |
|---|---|---|
| https://canvas.krsu.kg/doc/api/index.html | Canvas API docs hosted by another university (KRSU), not BTH. The Canvas API itself is generic Instructure, so the docs apply in principle. | Fetch failed (certificate error). Use the official Instructure docs instead. |
| https://github.com/AlexGustafsson/bth-api | Unofficial Node.js wrapper for BTH's student portal. Functions for exam registrations, course registrations, course results, coming exams, course plans, active courses. | Readable. Needs the `.BTHAT` login cookie from the student portal. README says it is unfinished, not production-ready, and not affiliated with BTH. Age and whether it still works are unverified. |
| https://plan.bth.se/programmes | Programme plans (likely source for next-semester courses). | Page is JavaScript-rendered. Nothing could be read. Needs a browser or a look at the network requests for a JSON API. |
| https://tentamen.bth.se/ | Exam registration and exam info. | Returned an application error, probably needs login. |
| https://bth.inspera.no/ | Inspera exam platform. | Only a login shell. Likely nothing useful without login. |
| https://www.bth.se/ | Public site: course syllabi, regulations. | Public. Good for RAG documents. |

### What this changes

- **Grades and exam results:** the bth-api project suggests the student portal
  has a results endpoint (`fetchCourseResults`). This is a possible alternative
  to Canvas or Ladok. It relies on a session cookie, so it is fragile and
  probably against the portal's intended use. Check BTH's terms and use only
  your own account.
- **Exams:** `fetchComingExams` and `tentamen.bth.se` could cover exam dates.
  Not verified.
- **Next-semester courses:** `plan.bth.se` is the most promising source, but
  it needs investigation first.
- Official, token-based Canvas API remains the cleanest option for deadlines.

## Setup and usage (implemented)

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                       # 36 tests, no network, no real data
.venv/bin/uniassist --mock summary     # try it on bundled mock data
.venv/bin/uniassist --mock ask "When is my next lecture?"   # needs Ollama running
```

Real data:

```bash
uniassist auth set                     # Canvas token + optional iCal URL (hidden input, stored 0600)
uniassist schedule import my.ics       # or: schedule add --title "Lecture 3" --start "2026-12-01 10:15" --course "Generative AI" --type lecture
uniassist tool get_upcoming_assignments   # check Canvas works without the LLM
uniassist chat -v                      # -v shows which tools were called
uniassist auth clear                   # delete local secrets (then revoke the token in Canvas)
```

Config: copy `config.example.toml` to `~/.config/uniassist/config.toml` (Canvas URL, model, programme file).
Next-semester courses come from a JSON file you provide (`{"semester": ..., "courses": [{"code","name","credits","period"}]}`).

Layout: `canvas.py` (read-only client) · `schedule.py` · `tools.py` (schemas + results) · `agent.py` (loop + memory)
· `llm.py` (Ollama, swappable) · `rag.py` (plug-in point for the separate RAG system) · `eval/run_eval.py`.

Evaluation: `python eval/run_eval.py` checks the data layer; add `--llm` for the full agent
(tool selection, exact match, guard against invented/injected answers) and `--llm --no-tools` for a no-tools baseline.
