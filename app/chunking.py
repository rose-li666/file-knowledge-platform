"""Paragraph/heading chunks with token windows and 30-token overlap."""
import re

def split_document(name, text, tokenizer):
    """Preserve headings/paragraphs; token-budgeted windows for long paragraphs."""
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    title = text.splitlines()[0].lstrip("# ").strip()
    heading = title
    chunks = []
    buffer = []

    def flush():
        if buffer:
            body = "\n\n".join(buffer)
            chunks.append({"document": name, "ordinal": len(chunks), "heading": heading,
                           "text": body, "input": f"{title}\n{heading}\n{body}"})
            buffer.clear()

    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        first = lines[0]
        if first.startswith("#") or re.match(r"^[一二三四五六七八九十]+、", first):
            flush()
            heading = first.lstrip("# ").strip()
            paragraph = "\n".join(lines[1:]).strip()
            if not paragraph:
                continue
        candidate = "\n\n".join(buffer + [paragraph])
        if len(tokenizer.encode(f"{title}\n{heading}\n{candidate}", add_special_tokens=True)) > 320:
            flush()
        prefix = f"{title}\n{heading}\n"
        budget = min(300, 480 - len(tokenizer.encode(prefix, add_special_tokens=True)))
        if budget < 40:
            raise ValueError("Document heading too long")
        tokens = tokenizer(paragraph, add_special_tokens=False, return_offsets_mapping=True)
        offsets = tokens["offset_mapping"]
        if len(offsets) > budget:
            flush()
            start = 0
            while start < len(offsets):
                end = min(start + budget, len(offsets))
                body = paragraph[offsets[start][0]:offsets[end - 1][1]]
                chunks.append({"document": name, "ordinal": len(chunks), "heading": heading,
                               "text": body, "input": prefix + body})
                if end == len(offsets):
                    break
                start = end - 30
        else:
            buffer.append(paragraph)
            flush()  # One semantic paragraph per chunk; avoid diluting rules with adjacent JSON/examples.
    flush()
    return chunks

