import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// Renders the light markdown the AI writes (headings, labelled parts, lists,
// bold and italic) as calm reading text. Anything unrecognised is shown as a
// plain paragraph, so nothing the model returns is ever dropped.

export type Block =
  | { kind: "heading"; text: string; id: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

function slug(text: string, used: Set<string>) {
  const base = text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 48) || "part";
  let id = base;
  for (let n = 2; used.has(id); n++) id = `${base}-${n}`;
  used.add(id);
  return id;
}

const HEADING_MD = /^#{1,4}\s+(.+?)\s*#*$/;
const HEADING_BOLD_LINE = /^\*\*(.+?)\*\*:?$/;
// "1. Research problem being addressed" on its own line: a short label, no sentence end.
const HEADING_NUMBERED_LABEL = /^\d+[.)]\s+(?:\*\*)?([A-Z][^.!?]{1,80}?)(?:\*\*)?:?$/;
const BULLET = /^[-*•]\s+(.*)$/;
const ORDERED = /^\d+[.)]\s+(.*)$/;

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  const used = new Set<string>();
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push({ kind: "list", ...list });
    list = null;
  };

  for (const raw of source.replace(/\r/g, "").split("\n")) {
    const line = raw.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading =
      line.match(HEADING_MD)?.[1] ?? line.match(HEADING_BOLD_LINE)?.[1] ?? line.match(HEADING_NUMBERED_LABEL)?.[1];
    if (heading) {
      flushParagraph();
      flushList();
      const text = heading.replace(/\*\*/g, "").replace(/^\d+[.)]\s+/, "").replace(/:$/, "").trim();
      blocks.push({ kind: "heading", text, id: slug(text, used) });
      continue;
    }
    const bullet = line.match(BULLET);
    const ordered = !bullet ? line.match(ORDERED) : null;
    if (bullet || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      if (!list || list.ordered !== isOrdered) {
        flushList();
        list = { ordered: isOrdered, items: [] };
      }
      list.items.push((bullet ?? ordered)![1]);
      continue;
    }
    if (list) {
      // A wrapped continuation of the last list item.
      list.items[list.items.length - 1] += ` ${line}`;
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  return blocks;
}

function inline(text: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)/g);
  return parts.map((part, i) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i} className="font-medium text-heading">{part.slice(2, -2)}</strong>;
    if (/^\*[^*]+\*$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>;
    if (/^`[^`]+`$/.test(part)) return <code key={i} className="rounded bg-raised px-1 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

export function RichText({ blocks, className }: { blocks: Block[]; className?: string }) {
  return (
    <div className={cn("reading", className)}>
      {blocks.map((block, i) => {
        if (block.kind === "heading") {
          return (
            <h3
              key={i}
              id={block.id}
              className="mb-2 mt-7 scroll-mt-32 font-sans text-[17px] font-semibold leading-snug first:mt-0"
            >
              {block.text}
            </h3>
          );
        }
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={i} className={cn("mb-4 space-y-1.5 pl-6 last:mb-0", block.ordered ? "list-decimal" : "list-disc", "marker:text-subtle-foreground")}>
              {block.items.map((item, j) => (
                <li key={j}>{inline(item)}</li>
              ))}
            </List>
          );
        }
        return (
          <p key={i} className="mb-4 last:mb-0">
            {inline(block.text)}
          </p>
        );
      })}
    </div>
  );
}
