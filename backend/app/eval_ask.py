"""
Test how well Ask answers questions about real papers, and score it.

Run from the backend folder:
    python -m app.eval_ask                 # ask the AI every test question, write a report
    python -m app.eval_ask --retrieval     # no AI: check the right passages are found
    python -m app.eval_ask --only pdf3     # one paper only

Each test question lists facts a good answer must contain (any one
spelling from each group), or is marked as not answerable from the paper,
where the right answer is an honest "the paper doesn't say". Answers that
show the model's reasoning instead of an answer fail outright.
The report is written to eval_ask_report.md (it is not committed).
"""
from __future__ import annotations

import argparse
import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.services.chunking import chunk_paper, paper_outline
from app.services.llm import LLMRequestError, _REASONING_START_RE, call_openrouter
from app.services.parser import detect_structure, parse_file
from app.services.prompts import build_ask_full_paper_prompt, build_ask_prompt
from app.services.retrieval import retrieve_relevant_chunks

PAPERS_DIR = Path(__file__).resolve().parents[2] / "test-pdfs"
REPORT = Path("eval_ask_report.md")
_HONEST_RE = re.compile(
    r"(does not|doesn't|do not|don't|not (?:mention|cover|discuss|report|say|state|specify|provide|include|describe|address)"
    r"|no (?:information|mention|details?)|isn't (?:covered|mentioned|stated|discussed)|is not (?:covered|mentioned|stated|discussed)"
    r"|not (?:part of|in) (?:the|this) paper|outside (?:the|this) paper)",
    re.IGNORECASE,
)


@dataclass
class Case:
    question: str
    kind: str
    expect: list[list[str]] = field(default_factory=list)  # every group must match one spelling
    unanswerable: bool = False
    history: list[dict] = field(default_factory=list)


CASES: dict[str, tuple[str, list[Case]]] = {
    "pdf3": ("pdf3_30pages.pdf", [
        Case("list the aspects present in this research paper like abstract, intro and so on", "structure",
             [["abstract"], ["introduction"], ["definition"], ["related research"], ["evaluation"],
              ["recommendation classes", "recommendation class"], ["shortcoming"], ["outlook", "summary"]]),
        Case("What is this paper about?", "overview",
             [["research-paper recommender", "research paper recommender"], ["survey", "review"], ["200"]]),
        Case("What are the main results?", "results",
             [["55"], ["content-based"], ["18"], ["collaborative"]]),
        Case("Which term weighting scheme was used most often?", "fact", [["tf-idf", "tf–idf", "tfidf"]]),
        Case("How many approaches did they review in depth, and out of how many?", "number", [["62"], ["96"]]),
        Case("What share of approaches neglected user modeling?", "number", [["81"]]),
        Case("What are the shortcomings the authors found in this research field?", "limitations",
             [["evaluation"], ["accuracy"], ["user model", "user-model"], ["reproduc", "re-implement", "implementation"]]),
        Case("What is the butterfly effect they talk about?", "concept",
             [["reproducib"], ["variation", "minor change", "small change", "small variation"]]),
        Case("What is content-based filtering?", "definition", [["content-based"], ["term", "word", "item", "feature"]]),
        Case("Which percentage of authors published only one paper on the topic?", "number", [["73"]]),
        Case("Which GPU did the authors use to train their neural network?", "unanswerable", unanswerable=True),
        Case("What accuracy does the proposed model reach on ImageNet?", "unanswerable", unanswerable=True),
        Case("And which of those was least common?", "follow-up", [["graph", "stereotyp", "co-occurrence", "global relevance"]],
             history=[{"role": "user", "content": "What recommendation classes were used and how often?"},
                      {"role": "assistant", "content": "Content-based filtering 55%, collaborative filtering 18%, graph-based 16%, and others."}]),
    ]),
    "resnet": ("pdf1_resnet_cvpr2016.pdf", [
        Case("What problem does this paper solve?", "overview", [["degradation", "harder to train", "difficult to train", "deeper"]]),
        Case("What is a residual block and how do shortcut connections work?", "method",
             [["identity"], ["shortcut"], ["f(x)", "residual function", "residual mapping"]]),
        Case("What top-5 error did the ensemble get on ImageNet?", "number", [["3.57"]]),
        Case("What was the deepest network they trained on ImageNet?", "number", [["152"]]),
        Case("Which datasets were used?", "fact", [["imagenet"], ["cifar"], ["coco", "pascal"]]),
        Case("List the sections of this paper", "structure",
             [["introduction"], ["related work"], ["deep residual learning"], ["experiments"]]),
        Case("How much electricity did training the models use?", "unanswerable", unanswerable=True),
    ]),
    "bert": ("pdf2_bert_naacl2019.pdf", [
        Case("What are the pre-training tasks of BERT?", "method", [["masked"], ["next sentence"]]),
        Case("What GLUE score does BERT reach?", "number", [["80.5"]]),
        Case("What F1 does BERT get on SQuAD v1.1?", "number", [["93.2"]]),
        Case("How many parameters does BERT-Large have?", "number", [["340"]]),
        Case("What are the main contributions?", "results", [["bidirectional"], ["pre-train", "pretrain"]]),
        Case("How does BERT do on ImageNet classification?", "unanswerable", unanswerable=True),
    ]),
}


def _matches(text: str, group: list[str]) -> bool:
    lower = text.lower().replace("‑", "-")
    return any(option in lower for option in group)


def score(case: Case, answer: str) -> tuple[float, str]:
    if _REASONING_START_RE.match(answer) or "<answer>" in answer.lower():
        return 0.0, "shows reasoning instead of an answer"
    if case.unanswerable:
        return (1.0, "honest") if _HONEST_RE.search(answer) else (0.0, "didn't say the paper doesn't cover it")
    missing = [group[0] for group in case.expect if not _matches(answer, group)]
    got = 1 - len(missing) / len(case.expect)
    return got, ("all facts" if not missing else "missing: " + ", ".join(missing))


def _prepare(filename: str):
    parsed = parse_file(filename, (PAPERS_DIR / filename).read_bytes())
    tables = [{"section": f"Table on page {t['page_number']}", "text": t["content"]} for t in parsed.structure.get("tables", [])]
    return parsed.raw_text, tables


async def run(only: str | None, retrieval_only: bool) -> None:
    lines = ["# Ask test report", ""]
    totals: list[float] = []
    for key, (filename, cases) in CASES.items():
        if only and key != only:
            continue
        raw_text, tables = _prepare(filename)
        chunks = chunk_paper(raw_text, None, extra_chunks=tables)
        outline = paper_outline(raw_text)
        sections = detect_structure(raw_text)["sections"]
        lines += [f"## {filename}", "", "| # | Kind | Score | Note | Question |", "|---|---|---|---|---|"]
        details = []
        for number, case in enumerate(cases, 1):
            previous = next((t["content"] for t in reversed(case.history) if t["role"] == "user"), "")
            picked = retrieve_relevant_chunks(case.question, chunks, top_k=10, context=previous)
            system, user = build_ask_prompt(case.question, picked, case.history, outline=outline, title=filename)
            if retrieval_only:
                answer = user  # do the passages (and outline) contain the facts?
                result, note = (1.0, "n/a") if case.unanswerable else score(case, user)
            else:
                _, full = build_ask_full_paper_prompt(case.question, sections, case.history, outline=outline,
                                                      title=filename, extras=tables)
                started = time.monotonic()
                try:
                    answer = await call_openrouter(system, user, max_tokens=1500, temperature=0.2,
                                                   long_context_user_prompt=full)
                except LLMRequestError as exc:
                    answer = f"(no answer: {exc})"
                result, note = score(case, answer)
                note += f" · {time.monotonic() - started:.0f}s"
                details += [f"### {key} {number}. {case.question}", "", answer if not retrieval_only else "", ""]
            totals.append(result)
            lines.append(f"| {number} | {case.kind} | {result:.0%} | {note} | {case.question} |")
            print(f"{key:<7} {number:>2} {case.kind:<12} {result:>4.0%}  {note}")
        lines += ["", *details]
    overall = sum(totals) / len(totals) if totals else 0
    lines.insert(2, f"Overall: **{overall:.0%}** over {len(totals)} questions" + (" (passages only)" if retrieval_only else ""))
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nOverall {overall:.0%}. Full answers in {REPORT.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval", action="store_true", help="check passages only, no AI calls")
    parser.add_argument("--only", choices=list(CASES), help="test one paper")
    args = parser.parse_args()
    asyncio.run(run(args.only, args.retrieval))
