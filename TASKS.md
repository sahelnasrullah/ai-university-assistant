# AI University Assistant: Tasks

Legend: `[ ]` to do. Mark `[x]` when done. Tasks marked **(verify)** depend on
an unverified assumption from the README. Do these first.

## Phase 0: Verify assumptions (do first)

- [x] **(verify)** Can a BTH student create a Canvas access token? Yes. URL is https://bth.instructure.com (verified 2026-11-26; canvas.bth.se is wrong).
- [x] **(verify)** Schedule: decided to be user-supplied (.ics import or manual entry), no TimeEdit dependency.
- [ ] **(verify)** Where do grades live? Check what Canvas shows. Check whether Ladok has any usable export.
- [ ] **(verify)** Where do next-semester courses come from? Programme plan on bth.se or another source.
- [x] Choose the core question set for version 1 (see Phase 6).
- [x] Choose the LLM runtime and model (for example Ollama + a quantised open model that supports tool calling).

## Phase 1: Foundation

- [x] Project structure, dependency management, config file for settings.
- [x] Secrets handling: Canvas token and iCal URL stored locally, never committed.
- [x] LLM client wrapper (local model, swappable).
- [x] Simple CLI chat loop to test the assistant end to end.

## Phase 2: Data connectors (read-only)

- [x] Canvas client: courses, assignments (`due_at`), announcements, modules, files, grades.
- [x] Handle pagination, rate limits, and error responses.
- [x] Schedule client: fetch and parse iCal/TimeEdit into events (start, end, course, room, type).
- [x] Time handling: time zones (Europe/Stockholm), "next", "today", "this week".
- [x] Local cache so repeated questions do not hit the APIs each time.
- [x] Course catalogue / programme plan loader for next-semester courses.

## Phase 3: Tool-calling layer (structured questions)

- [x] Tool definitions with clear schemas, for example:
  - [x] `get_upcoming_assignments(course?, days?)`
  - [x] `get_assignment_due_date(course, assignment)`
  - [x] `get_next_lecture(course?)`
  - [x] `get_schedule(date_range)`
  - [x] `get_grades(course?)`
  - [x] `get_next_semester_courses()`
- [x] Agent loop: model picks a tool, runs it, reads the result, answers.
- [x] Fuzzy matching for course and assignment names ("assignment 2 in gen ai").
- [x] Rule: if the tool returns nothing, say so. Never invent dates or grades.

## Phase 4: RAG layer (unstructured questions)

- [ ] Ingest course documents: syllabi, course PM, lecture slides, announcements, regulations.
- [ ] Chunking strategy and metadata (course, document, page, date).
- [ ] Embeddings and a vector store.
- [ ] Retrieval with source citations in the answer.
- [ ] Handles: "What is the lecture about?", "What do I need to prepare?", grading rules, learning outcomes.
- [ ] Re-index when new files or announcements appear.

## Phase 5: Orchestration

- [x] Router: decide tool call, RAG, or both (for example "What do I need to prepare for my next lecture?" = find the lecture with a tool, then retrieve its content with RAG).
- [x] Conversation memory for follow-up questions ("and the one after that?").
- [x] Answers that show their source (API, calendar, or document + page).

## Phase 6: Core questions for version 1

- [ ] When is my next lecture?
- [ ] What do I need to prepare for it?
- [ ] What is the lecture about?
- [x] When is my next assignment due? / When is Assignment X in course Y due? (works on real Canvas data)
- [ ] What grade did I get on exam X? (depends on the grades source)
- [ ] Which courses am I reading next semester? (depends on the source)

## Phase 7: Evaluation

- [x] Build a test set with ground truth from the APIs and documents.
- [x] Metrics: exact-match for dates and grades, correct tool selection rate.
- [ ] Metrics: RAGAS faithfulness and relevance for document questions.
- [ ] Baseline: plain RAG versus RAG + tools on date and schedule questions.
- [x] Mock Canvas dataset so tests do not need real student data.

## Phase 8: Privacy and safety

- [x] Everything runs locally by default. No personal data sent to external APIs.
- [x] Read-only access. The assistant never changes anything.
- [x] Token can be revoked and removed easily. Document how.
- [x] Guard against prompt injection from announcements or documents (treat fetched text as data, not instructions).

## Phase 9: Interface and polish (later)

- [x] Simple UI (web or chat) after the CLI works.
- [x] Onboarding: link your account once (paste token and schedule URL).
- [x] Proactive features (optional): daily summary, deadline reminders.
- [x] README with setup instructions.

## Phase 10: More Canvas tools (read-only)

- [x] `get_calendar_events(start, end)`: teacher-created events (exams, guest lectures). Check BTH actually fills it.
- [x] `get_missing_submissions`: replaces the 14-day overdue heuristic.
- [x] `get_submission_feedback(course, assignment)`: score, teacher comments, late/missing flags.
- [x] `get_todo_items`: Canvas's own to-do list, as a cross-check.
- [x] `get_course_syllabus`, `get_pages`, `list_files` (files are the bridge to the RAG work).
- [x] `get_teachers(course)`; inbox only as an opt-in.
- [x] Verify each endpoint against the real BTH Canvas before relying on it.
- [x] Choose how to show only current courses (old terms currently leak into results).

## Phase 11: Learning mode (tutor, not solver)

Goal: from an assignment, help the student learn and do the work, never hand over a submission-ready answer.

- [x] Show the course/BTH AI policy before offering help (needs the syllabus via RAG).
- [x] Actions per assignment: Understand it, Plan it (steps + time before the deadline), Hint (staged 1 to 3), Quiz me, Review my draft.
- [x] Enforce the no-solution rule in code, not only in the prompt: no tool or action returns a full solution; hints are staged; draft review points out problems without rewriting.
- [x] Tests that try to bypass it ("just give me the code", "ignore your rules") and check no full solution comes out.
- [x] Decide what the assistant logs (nothing personal leaves the machine).

## Phase 12: Click interface

- [x] Pick the UI: small local web app (recommended) or terminal UI.
- [x] Flow: courses, assignments, assignment details, action buttons (see Phase 11).
- [x] Dashboard: today's schedule, deadlines this week, new announcements.
- [x] Keep it local-only (bind to 127.0.0.1), token stays in the existing secrets file.

## Still open from earlier phases

- [ ] **(verify)** Grades: Canvas only shows grades teachers enter. Ladok has no known student API.
- [ ] **(verify)** Next-semester courses: plan.bth.se is JavaScript-rendered; for now a student-provided JSON file.
- [ ] Install Ollama, pull a tool-calling model, run `uniassist chat -v` and `eval/run_eval.py --llm` (never run end to end yet).
- [ ] RAG layer (Phase 4), being built separately, plugs in through `src/uniassist/rag.py`.
- [ ] Wire the retriever into `build_context()` in `cli.py`.
- [ ] RAGAS metrics and plain-RAG vs RAG+tools baseline (need the RAG system).

## Suggested next order

1. Install Ollama and run the agent on real data (finds the real problems fastest).
2. Phase 10 tools that answer everyday questions (calendar, missing submissions, feedback).
3. Phase 11 learning mode, then Phase 12 UI on top of it.
4. Connect the RAG system when it is ready.

## Suggested build order

Phase 0, then 1, then 2 (Canvas deadlines first), then 3, then 4, then 5, then 6, then 7.
Add 8 as you go and 9 last. A first usable milestone is: "When is my next assignment due?" answered correctly from Canvas through a tool call.

## Status notes (2026-11-25)

- Built everything except RAG (Phase 4, done separately). `src/uniassist/rag.py` is the plug-in
  point: pass a `Retriever` and the `search_course_documents` tool appears automatically.
- Schedule is user-supplied (local `.ics`, iCal URL, or manual `schedule add`), so no TimeEdit dependency.
- Not done: simple web UI (Phase 9); the RAGAS metrics and the plain-RAG vs RAG+tools baseline (need your RAG).
- Still unverified (needs your real account): BTH Canvas token creation, real Canvas URL, Ladok/grades source,
  `uniassist --llm` end to end with a pulled Ollama model (Ollama is not installed here).

## Status update (2026-11-26): built autonomously

Done and tested (105 tests): Canvas tools (checked against the real BTH Canvas), current-course filter, TimeEdit
schedule handling (.html to .ics, group-schedule filtering), planner (priorities, clashes, study plan), change
alerts + deadline warnings + desktop notifications (+ systemd unit generator), briefing/week views, learning mode
with code-level guards, local web app, evaluation (`--guard` added).

Decisions made without asking: nothing is logged beyond the local hint-level state
(`~/.config/uniassist/tutor_state.json`); `timers` only prints units (you install them); hint levels persist per assignment.

Still open:
- [ ] Install Ollama + a tool-calling model, then run `eval/run_eval.py --llm` and `--llm --no-tools`
- [ ] Click through the web app in a real browser (`uniassist web --open`)
- [ ] Enable timers (`uniassist timers`) once happy with `uniassist notify`
- [ ] Room finder, exam registration, study regulations Q&A (the last one is RAG)
- [ ] Connect the RAG retriever in `build_context()` (see `rag.py`)
- [ ] Known guard gaps (see `eval/run_eval.py --guard`): obfuscated and indirect requests
