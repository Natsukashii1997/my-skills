#!/usr/bin/env python3
"""Read-only, conservative snapshot comparison. Never proves semantic fidelity.

Usage: python3 check_fidelity.py BEFORE AFTER [--mode refine|polish|format]
       [--protected '["试点中可能有效", "未包含人力成本"]']

Inputs are UTF-8 files: lark docs +fetch JSON or multi-root Feishu XML with a
leading title. Only counts, document IDs, revisions and fixed diagnostic codes
are printed. No source text, links or resource tokens are emitted. Exit 2 means
invalid/incomplete input, 1 a hard constraint failed, 0 means manual review is
still needed. An exit of 0 and equal counts NEVER mean semantic equivalence.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


class InputError(ValueError):
    """A fixed diagnostic code, never raw input or parser exception text."""


TEXT_BLOCKS = {"title", "p", "li", "pre", "td", "th", "code-block"} | {
    "h" + str(n) for n in range(1, 7)
}
INLINE = {"b", "strong", "em", "i", "u", "s", "del", "span", "code", "a",
          "cite", "mention", "user", "br", "sub", "sup", "math"}
RESOURCE_ATTRIBUTES = {"token", "file-token", "image-token", "doc-id",
                       "board-id", "sheet-id", "file-id", "media-id"}
URL_ATTRIBUTES = {"href", "url"}
BAD_FLAGS = {"truncated", "istruncated", "partial", "ispartial", "hasmore",
             "fragment", "isfragment", "incomplete", "error", "errors"}
FALSE_FLAGS = {"complete", "iscomplete", "fulldocument"}
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[,.]\d+)*(?:%|％)?")
URL_RE = re.compile(r"https?://[^\s<>\"'，。；、）\]\}]+")


@dataclass
class Snapshot:
    document_id: str
    revision: object
    input_kind: str
    blocks: list
    numbers: Counter
    links: Counter
    resources: Counter


def fail(code):
    raise InputError(code)


def flag_name(name):
    return name.lower().replace("-", "").replace("_", "")


def reject_flags(value):
    """Check control metadata only; document prose stays an opaque string."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = flag_name(key)
            if normalized in BAD_FLAGS and item not in (None, False, "", [], {}):
                fail("input_reports_error_or_incompleteness")
            if normalized in FALSE_FLAGS and item is False:
                fail("input_reports_incompleteness")
            if normalized == "ok" and item is not True:
                fail("input_reports_failure")
            if normalized in {"status", "state"} and isinstance(item, str) and item.lower() in {
                    "error", "failed", "partial", "truncated", "incomplete"}:
                fail("input_reports_error_or_incompleteness")
            reject_flags(item)
    elif isinstance(value, list):
        for item in value:
            reject_flags(item)


def tag(node):
    return node.tag.rsplit("}", 1)[-1].lower()


def normalize(text, preserve_lines=False):
    # Code indentation is meaningful; ordinary line-wrapping whitespace is not.
    if preserve_lines:
        return text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def visible_inline(node):
    if tag(node) == "br":
        return "\n"
    output = node.text or ""
    # Linked document labels and mentions can be represented only as attributes.
    if tag(node) in {"cite", "mention", "user"} and not output and not len(node):
        output = node.get("title") or node.get("name") or ""
    for child in node:
        output += visible_inline(child) + (child.tail or "")
    return output


def text_blocks(root):
    """Keep each textual block separate, including nested paragraphs and cells.

    Inline styling is ignored. Blocks never concatenate across boundaries, so
    <p>AB</p><p>C</p> differs from <p>A</p><p>BC</p>. Table cell and row boundaries
    remain explicit. Headings and paragraphs may exchange presentation styles.
    """
    result = []

    def visit(node, in_code=False):
        kind = tag(node)
        is_code = in_code or kind in {"pre", "code-block"}
        if kind == "tr":
            result.append(("row-start", ""))
        if kind in {"td", "th"}:
            result.append(("cell-start", ""))
        pending = [node.text or ""]

        def flush():
            text = normalize("".join(pending), is_code)
            if text:
                result.append(("code" if is_code else "text", text))
            pending.clear()

        for child in node:
            child_tag = tag(child)
            # Inline-only descendants do not create another text block.
            has_blocks = any(tag(d) in TEXT_BLOCKS for d in child.iter() if d is not child)
            if child_tag in INLINE and not has_blocks:
                pending.append(visible_inline(child))
            else:
                flush()
                visit(child, is_code)
            pending.append(child.tail or "")
        flush()
        if kind in {"td", "th"}:
            result.append(("cell-end", ""))
        if kind == "tr":
            result.append(("row-end", ""))

    visit(root)
    return result


def read_snapshot(path):
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        fail("input_not_readable_utf8")
    if not raw.strip():
        fail("empty_input")
    document_id, revision, input_kind = None, None, "xml_fragment"
    xml = raw
    if raw.lstrip().startswith(("{", "[")):
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            fail("invalid_json")
        if not isinstance(data, dict):
            fail("unsupported_json_shape")
        reject_flags(data)
        if data.get("ok") is not True:
            fail("missing_success_envelope")
        try:
            doc = data["data"]["document"]
            xml = doc["content"]
            document_id = doc["document_id"]
            revision = doc.get("revision_id")
        except (KeyError, TypeError, AttributeError):
            fail("unsupported_json_shape")
        if not isinstance(xml, str) or not isinstance(document_id, str):
            fail("invalid_document_fields")
        if not ID_RE.fullmatch(document_id):
            fail("invalid_document_id")
        if revision is not None and (isinstance(revision, bool) or
                                    not isinstance(revision, (int, str)) or
                                    not str(revision).isdigit()):
            fail("invalid_revision")
        input_kind = "fetch_document_envelope"
    elif not raw.lstrip().startswith("<"):
        fail("unsupported_input_format")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.IGNORECASE):
        fail("dtd_or_entity_forbidden")
    # A CLI transcript or truncated parser output must not be guessed into XML.
    if re.search(r"<\?xml\b", xml, re.IGNORECASE):
        fail("xml_declaration_not_supported_in_fragment")
    try:
        root = ET.fromstring("<snapshot-root>" + xml + "</snapshot-root>")
    except (ET.ParseError, RecursionError):
        fail("invalid_xml")
    if (root.text or "").strip() or any((c.tail or "").strip() for c in root):
        fail("text_outside_document_blocks")
    children = list(root)
    if not children or tag(children[0]) != "title":
        fail("partial_fragment_missing_leading_title")
    if sum(tag(n) == "title" for n in root.iter()) != 1:
        fail("multiple_document_titles")
    title_id = children[0].get("id", "")
    if not ID_RE.fullmatch(title_id):
        fail("missing_or_invalid_title_document_id")
    if document_id is not None and document_id != title_id:
        fail("document_id_title_mismatch")
    document_id = document_id or title_id
    for node in root.iter():
        normalized = flag_name(tag(node))
        if normalized in BAD_FLAGS:
            fail("xml_reports_error_or_incompleteness")
        for key, value in node.attrib.items():
            key = flag_name(key)
            if key in BAD_FLAGS and value.lower() not in {"", "false", "0", "none"}:
                fail("xml_reports_error_or_incompleteness")
            if key in FALSE_FLAGS and value.lower() in {"false", "0"}:
                fail("xml_reports_incompleteness")
    blocks = text_blocks(root)
    texts = [value for _, value in blocks if value]
    links, resources = Counter(), Counter()
    numbers = Counter(number for text in texts for number in NUMBER_RE.findall(text))
    for text in texts:
        links.update(URL_RE.findall(text))
    for node in root.iter():
        for key, value in node.attrib.items():
            key = key.lower().replace("_", "-")
            if key in URL_ATTRIBUTES and value:
                links[value] += 1
            if key == "src" and value:
                if re.match(r"https?://", value):
                    links[value] += 1
                resources[(tag(node) + ".src", value)] += 1
            if key in RESOURCE_ATTRIBUTES and value:
                resources[(key, value)] += 1
    return Snapshot(document_id, revision, input_kind, blocks, numbers, links, resources)


def differences(before, after):
    return {"removed_occurrences": sum((before - after).values()),
            "added_occurrences": sum((after - before).values()),
            "before_occurrences": sum(before.values()),
            "after_occurrences": sum(after.values())}


def compare(before, after, protected, mode):
    changes = {name: differences(getattr(before, name), getattr(after, name))
               for name in ("numbers", "links", "resources")}
    before_texts = [text for _, text in before.blocks if text]
    after_texts = [text for _, text in after.blocks if text]
    absent_source = [index for index, phrase in enumerate(protected)
                     if not any(phrase in text for text in before_texts)]
    if absent_source:
        fail("protected_phrase_not_present_in_source_block")
    missing = [index for index, phrase in enumerate(protected)
               if not any(phrase in text for text in after_texts)]
    sequence_equal = before.blocks == after.blocks
    failures = []
    if missing:
        failures.append("protected_phrases_missing")
    if mode == "format" and not sequence_equal:
        failures.append("format_text_block_sequence_changed")
    def metadata(snapshot):
        return {"document_id": snapshot.document_id, "revision": snapshot.revision,
                "input_kind": snapshot.input_kind,
                "completeness": "unverified_requires_read_coverage_check",
                "text_block_count": sum(bool(t) for _, t in snapshot.blocks)}
    return {"status": "fail" if failures else "needs_review", "mode": mode,
            "before": metadata(before), "after": metadata(after),
            "hard_constraint_failures": failures,
            "protected": {"count": len(protected), "missing_indices": missing},
            "format_text_sequence_equal": sequence_equal,
            "review_signals": changes, "semantic_fidelity": "not_evaluated",
            "note": "Counts cannot prove meaning or full read coverage; inspect source and result."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--mode", choices=["refine", "polish", "format"], default="refine")
    parser.add_argument("--protected", default="[]", help="JSON array of exact protected strings")
    args = parser.parse_args(argv)
    try:
        try:
            protected = json.loads(args.protected)
        except (ValueError, RecursionError):
            fail("invalid_protected_json")
        if not isinstance(protected, list) or any(not isinstance(x, str) or not x for x in protected):
            fail("protected_must_be_nonempty_strings")
        result = compare(read_snapshot(args.before), read_snapshot(args.after), protected, args.mode)
    except (InputError, RecursionError) as exc:
        code = str(exc) if isinstance(exc, InputError) else "input_nesting_too_deep"
        print(json.dumps({"status": "invalid_input", "error": code}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
