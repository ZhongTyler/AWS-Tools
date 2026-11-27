"""Editable display fields in the research study v1 source format."""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Field:
    path: tuple
    role: str
    text: str

    @property
    def id(self):
        return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in self.path)

    @property
    def location(self):
        # Positional context goes to the editor. Source keys and paths stay local.
        if self.path[0] == "sources":
            return "sources"
        return "/".join(str(part + 1) if isinstance(part, int) else part for part in self.path)

    def replace(self, source, text):
        parent = source
        for part in self.path[:-1]:
            parent = parent[part]
        parent[self.path[-1]] = text


LOCKED = None
SOURCE = {"label": "source display label", "url": LOCKED, "path": LOCKED,
          "reader_path": LOCKED, "sha256": LOCKED}
TOC = {
    "type": LOCKED, "leading": [LOCKED], "trailing": [LOCKED],
    "groups": [{"id": LOCKED, "title": "contents group title", "sections": [LOCKED],
                "chapter": {"opening": LOCKED, "closing": LOCKED}}],
}
BLOCKS = {
    "p": {"text": "paragraph"},
    "note": {"text": "reader note"},
    "flow": {"items": ["flow step label"]},
    "table": {"headers": ["table header"], "rows": [["table cell"]], "widths": [LOCKED]},
    "image": {"src": LOCKED, "small_src": LOCKED, "alt": "image alt text", "caption": "image caption",
              "html_caption": "web image caption", "markers": [{"x": LOCKED, "y": LOCKED, "label": "image marker label"}]},
    "links": {"items": [("link display label", LOCKED)]},
}
SECTION = {"id": LOCKED, "title": "section and contents title", "subtitle": "section subtitle",
           "reader_goals": ["reader guide"], "references": [LOCKED], "blocks": [BLOCKS]}
STUDY = {"schema": LOCKED, "title": "document title", "subtitle": "document subtitle",
         "short_title": "running title", "edition": "edition text", "reader": "reader introduction",
         "toc_layout": TOC, "text_toc": TOC, "sections": [SECTION], "sources": SOURCE}


def fields(source):
    if not isinstance(source, dict) or type(source.get("schema")) is not int or source["schema"] != 1:
        raise ValueError("unsupported_study_schema")
    result = list(walk(source, STUDY))
    sections = source.get("sections", [])
    ids = [section.get("id") for section in sections]
    if not ids or any(not isinstance(section_id, str) or not section_id for section_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("invalid_study_section_ids")
    sources = source.get("sources", {})
    for section in sections:
        if any(not isinstance(key, str) or key not in sources for key in section.get("references", [])):
            raise ValueError("unknown_study_source_reference")
        for block in section.get("blocks", []):
            if block["type"] == "links" and any(
                not isinstance(key, str) or key not in sources for _, key in block.get("items", [])
            ):
                raise ValueError("unknown_study_source_reference")
            if block["type"] == "table":
                headers = block.get("headers")
                rows = block.get("rows")
                if not headers or rows is None or any(len(row) != len(headers) for row in rows):
                    raise ValueError("invalid_study_table_shape")
    for field in ("toc_layout", "text_toc"):
        if field in source:
            check_toc(source[field], ids)
    return result


def check_toc(toc, section_ids):
    if toc.get("type") != "grouped":
        raise ValueError("unsupported_study_toc")
    order = list(toc.get("leading", []))
    group_ids = set()
    for group in toc.get("groups", []):
        if "id" in group:
            group_id = group["id"]
            if not isinstance(group_id, str) or not group_id or group_id in group_ids:
                raise ValueError("invalid_study_toc_group_id")
            group_ids.add(group_id)
        members = group.get("sections", [])
        order.extend(members)
        if "chapter" in group:
            chapter = group["chapter"]
            if (not members or set(chapter) != {"opening", "closing"}
                    or chapter["opening"] != members[0] or chapter["closing"] != members[-1]):
                raise ValueError("invalid_study_chapter_references")
    order.extend(toc.get("trailing", []))
    if order != section_ids:
        raise ValueError("invalid_study_toc_references")


def walk(value, schema, path=()):
    if schema is BLOCKS:
        kind = value.get("type") if isinstance(value, dict) else None
        if not isinstance(kind, str) or kind not in BLOCKS:
            raise ValueError("unsupported_study_block")
        schema = {"type": LOCKED, **BLOCKS[kind]}
    if schema is LOCKED:
        if (type(value) not in (str, int, float, bool) and value is not None
                or type(value) is float and not isfinite(value)):
            raise ValueError("invalid_study_structural_value")
    elif isinstance(schema, str):
        if not isinstance(value, str) or "\0" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("invalid_study_display_text")
        if value.strip():
            yield Field(path, schema, value)
    elif isinstance(schema, (list, tuple)):
        if not isinstance(value, list) or isinstance(schema, tuple) and len(value) != len(schema):
            raise ValueError("invalid_study_list_shape")
        members = enumerate(schema if isinstance(schema, tuple) else [schema[0]] * len(value))
        for index, item_schema in members:
            yield from walk(value[index], item_schema, (*path, index))
    else:
        if not isinstance(value, dict):
            raise ValueError("invalid_study_object_shape")
        if path == ("sources",):
            for key, item in sorted(value.items()):
                yield from walk(item, SOURCE, (*path, key))
        else:
            if value.keys() - schema.keys():
                raise ValueError("unsupported_study_field")
            for key, item_schema in schema.items():
                if key in value:
                    yield from walk(value[key], item_schema, (*path, key))
