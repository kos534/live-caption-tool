"""Answers questions heard in the captions using the OpenAI API.

The caption window hands over the caption text spoken since the previous Answer click; this module
streams the model's answer back through a queue that the Tk thread polls (Tk isn't thread-safe).
"""

import logging
import os
import queue
import re
import threading

log = logging.getLogger(__name__)

# The instructions the model gets before the user's profile. Editable in ⚙ Settings → Answer
# prompt; an empty setting means this default.
DEFAULT_ANSWER_PROMPT = """\
You are my live copilot on calls with recruiters, hiring managers, or my new team (screens, interviews, onboarding calls). I read your reply out loud as my own words.

What you get
Each message is an automatic speech-to-text transcript of the latest part of the call. It has no speaker labels, it mixes the other person's voice with mine, and some words are misheard. Work out who said what from context. They're the one explaining how things work on their side. I'm the one asking about their process, like "do we buy our own tools?" or "which brand does the team use?". Never answer those questions, they're mine. If the latest lines are my own question, just give a short natural follow-on, like thanks or a quick clarification. Otherwise reply to the latest thing they said or asked. If a phrase is garbled, ignore it rather than guessing what it meant.

First, decide what kind of moment it is
- They're explaining something (the company, product, role, tools, process, safety rules, logistics): 1–2 sentences. React the way a person would: say what I'll do with it ("Okay, I'll grab boots with that rating before I start"), a quick related bit from my own work, or just a simple okay. Don't praise or judge what they said, and don't restate or summarize it. No questions.
- They ask if I have questions: say I'm good in one sentence, or ask one short, specific question about something they actually mentioned.
- They ask about my experience: 4–6 sentences.
- They ask about my approach or how I'd handle something: 3–5 sentences.
- "Tell me about yourself": 6–8 sentences.
- Small talk or a quick yes/no check: one short sentence.
When in doubt, go shorter.

How it should sound
Very natural, light, cheerful, Asian-American conversational, native-level English. Like talking, not writing. Short, simple sentences, plain words, contractions. No jargon, buzzwords, clichés, filler phrases, or resume-style language. No explanations, summaries, or bullet points. Don't sound like AI. Spontaneous, not rehearsed.

Don't fall into a template
Every reply should start differently and have a different shape. Never open with a stock acknowledgment like "Got it", "That makes total sense", "That totally clicks", "Yeah, X is definitely key", "Absolutely", or "Great question". Never end with a wrap-up or verdict line like "Sounds like a smart approach", "It's pretty practical", "Better safe than sorry", or "Thanks for that!". Don't rate or compliment their process ("that's smart", "that's key", "game changer", "I'm with you on that"). Don't echo their words back to them. Just say the thing, the way a person would.

When they ask about my experience
Always answer "yes" implicitly. Use real, specific projects from companies on my resume. Mention actual org names, departments, and teams where relevant. Don't invent projects or tailor fake experience to the JD. If something isn't obvious on the resume, first find a related real project. If still unclear, research the company and ground the answer realistically. Never say "I don't have experience with that."

When they ask about my approach or general understanding
Present tense only, like "I usually start by…" or "I'd normally look at…". Don't reference past jobs or projects in these answers.

Structure
Don't go company-by-company or chronological. Keep it loose, slightly out of order, but clear and confident.

Motivation cues (only when they ask why I'm looking, and never all at once)
I'm tired of consulting work that keeps switching clients and projects. The company shifted into low-code AI / vibe-coding, which pushed me to look elsewhere.

When they ask "tell me about yourself"
Share the experiences that connect directly to what they're hiring for. Highlight the strengths that solve their problems, and make the alignment easy to see. Describe my dream job as the exact job they're offering. Don't oversell, and don't make it sound memorized. Be intentional and strategic.

Never
Resume stats, copied phrasing, generic success language, "excited about this opportunity" type lines, or a salesy, wheezy, over-polished tone. Never make up details they didn't say.

Reply with only the words I should say."""


def build_system_prompt(settings) -> str:
    """The answer prompt (custom or default), plus the user's personal info, resume and JD if set."""
    if settings is None:
        return DEFAULT_ANSWER_PROMPT
    prompt = settings.answer_prompt.strip() or DEFAULT_ANSWER_PROMPT
    info = [
        f"{label}: {value}"
        for label, value in (
            ("Name", settings.name),
            ("Birthday", settings.birthday),
            ("Address", settings.address),
            ("University", settings.university),
        )
        if value.strip()
    ]
    sections = []
    if info:
        sections.append("## About the user\n" + "\n".join(info))
    if settings.resume_text.strip():
        sections.append("## The user's resume\n" + settings.resume_text.strip())
    if settings.job_description.strip():
        sections.append("## Job description\n" + settings.job_description.strip())
    return "\n\n".join([prompt] + sections)


def build_user_message(question: str, history: list) -> str:
    """The latest transcript segment, with earlier segments (if any) as labeled background."""
    if not history:
        return question
    earlier = "\n\n".join(history)
    return (
        f"Earlier in the call (background only, already handled):\n{earlier}\n\n"
        f"Latest part of the call (reply to this):\n{question}"
    )


def load_api_key(key_file, settings=None) -> str:
    """The key from Settings, else OPENAI_API_KEY, else the first line of key_file (next to the app)."""
    key = (settings.openai_api_key if settings is not None else "").strip()
    if key:
        return key
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if key:
        return key
    try:
        return key_file.read_text(encoding="utf-8-sig").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


# Added after the user's prompt when web search is on: search results are background only, the
# answer is still spoken by the user, so no links or citation markers.
WEB_SEARCH_NOTE = (
    "You can search the web. Use it when the answer depends on facts you don't have, such as what "
    "the interviewer's company does, its products, news or culture. Use what you find only as "
    "background: never include links, URLs, source names or citation markers in the answer."
)

_CITATION = re.compile(r"\s*\(\[[^\]]*\]\([^)]*\)\)|\[([^\]]*)\]\(https?://[^)]*\)|\s*\(?https?://\S+\)?")


def strip_citations(text: str) -> str:
    """Remove markdown links / bare URLs that web search answers sometimes include anyway."""
    return re.sub(r"[ \t]{2,}", " ", _CITATION.sub(lambda m: m.group(1) or "", text)).strip()


class Answerer:
    def __init__(
        self,
        model: str,
        key_file,
        settings=None,
        history_turns: int = 3,
        max_tokens: int = 600,
        web_search: bool = True,
        web_search_context: str = "low",
    ):
        self.model = model
        self.key_file = key_file
        self.settings = settings  # UserSettings: API key and the user's profile, read on every request
        self.history_turns = history_turns  # earlier transcript segments sent along as context
        self.max_tokens = max_tokens
        self.web_search = web_search
        self.web_search_context = web_search_context
        # (request_id, kind, text): kind is "delta", "status" (e.g. searching), "done" or "error"
        self.events = queue.Queue()
        # Earlier transcript segments, oldest first. The model's own earlier answers are deliberately
        # not sent back: it copies their shape, and every reply ends up following one template.
        self._history = []
        self._client = None
        self._client_key = None

    def reset(self):
        """Forget the earlier conversation (the transcript was cleared)."""
        self._history = []

    def ask(self, request_id: int, question: str):
        """Start answering `question` in the background; results arrive on self.events."""
        history = list(self._history[-self.history_turns:]) if self.history_turns else []
        threading.Thread(target=self._run, args=(request_id, question, history), daemon=True).start()

    def _get_client(self):
        key = load_api_key(self.key_file, self.settings)
        if not key:
            raise RuntimeError("No OpenAI API key: add it in ⚙ Settings → Security")
        if self._client is None or key != self._client_key:
            from openai import OpenAI  # imported lazily so startup isn't slowed down

            # Web searches can take a while, so allow more time than a plain answer needs.
            self._client = OpenAI(api_key=key, timeout=90.0, max_retries=1)
            self._client_key = key
        return self._client

    def _run(self, request_id: int, question: str, history: list):
        try:
            client = self._get_client()
            instructions = build_system_prompt(self.settings)
            messages = [{"role": "user", "content": build_user_message(question, history)}]
            try:
                answer = self._stream(client, request_id, instructions, messages, self.web_search)
            except Exception as exc:
                if not (self.web_search and _is_tool_unsupported(exc)):
                    raise
                # This model can't use web search: answer without it rather than failing.
                log.warning("Web search unavailable for %s (%s); answering without it", self.model, exc)
                answer = self._stream(client, request_id, instructions, messages, False)
            self._history.append(question)
            self._history = self._history[-max(1, self.history_turns):]
            self.events.put((request_id, "done", answer))
        except Exception as exc:  # network, auth, quota, bad model name...
            log.warning("Answer request failed: %s", exc)
            self.events.put((request_id, "error", _describe(exc)))

    def _stream(self, client, request_id: int, instructions: str, messages: list, web_search: bool) -> str:
        """Stream one Responses API answer onto self.events; returns the cleaned full text."""
        kwargs = {}
        if web_search:
            instructions = instructions + "\n\n" + WEB_SEARCH_NOTE
            kwargs["tools"] = [{"type": "web_search", "search_context_size": self.web_search_context}]
        stream = client.responses.create(
            model=self.model,
            instructions=instructions,
            input=messages,
            max_output_tokens=self.max_tokens,
            stream=True,
            **kwargs,
        )
        parts = []
        for event in stream:
            if event.type == "response.output_text.delta":
                parts.append(event.delta)
                self.events.put((request_id, "delta", event.delta))
            elif event.type == "response.web_search_call.searching":
                self.events.put((request_id, "status", "searching the web"))
            elif event.type in ("response.failed", "error"):
                message = getattr(getattr(event, "response", None), "error", None) or getattr(event, "message", "")
                raise RuntimeError(getattr(message, "message", None) or str(message) or "OpenAI request failed")
        return strip_citations("".join(parts))


def _is_tool_unsupported(exc: Exception) -> bool:
    try:
        import openai
    except ImportError:
        return False
    return isinstance(exc, openai.BadRequestError) and "web_search" in str(exc).lower()


def _describe(exc: Exception) -> str:
    """A short, user-facing reason for a failed request."""
    try:
        import openai
    except ImportError:
        return "The openai package isn't installed"
    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI rejected the API key"
    if isinstance(exc, openai.RateLimitError):
        return "OpenAI rate limit or quota reached"
    if isinstance(exc, openai.NotFoundError):
        return "OpenAI model not found (check OPENAI_MODEL in config.py)"
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
        return "Couldn't reach OpenAI (check the internet connection)"
    if isinstance(exc, openai.APIStatusError):
        return f"OpenAI error {exc.status_code}"
    return str(exc) or exc.__class__.__name__
