"""
SRS Reader for the Agentic Cleanroom Specification Generator Agent.

Responsibilities (all deterministic — no LLM involved):
  - Recursively parse an SRS XML at any nesting depth.
  - Assign every node a stable ID: the real `id` attribute if present,
    otherwise a position-based fallback.
  - Tag each node as "section" (grouping header) or "requirement".
  - Extract functional requirements ONLY from:
      * "Functional Requirements" sections (legacy req_document, e.g. video search),
      * ``SystemRequirements`` / ``<Feature>`` blocks (e.g. DineOut, Gemini),
      * PEPPOL/VCD ``req_document`` subsections with MUST/SHOULD/SHALL itemize bullets.

`<itemize>` handling is section-aware: everywhere else an itemize is an OVERVIEW list
and is skipped (so it never produces phantom requirements), but inside a
"Functional Requirements" section the itemize items ARE the requirements.

The LLM is intentionally kept OUT of IDs, structure, and grouping so that
those can never drift or hallucinate. The LLM's job downstream is only
interpretation (e.g. inferring inputs/outputs for feature-style SRS).
"""

import re
from pathlib import Path

from lxml import etree


# --------------------------------------------------------------------------
# low-level helpers
# --------------------------------------------------------------------------
def _strip_ns(tag) -> str:
    """Drop the namespace prefix from a tag name (lxml gives '{ns}tag').

    Comment / processing-instruction nodes carry a *callable* tag (not a str) — those
    appear in PDF-exported XML (e.g. `<?xpacket?>`). Treat them as nameless so callers
    iterating mixed children skip them instead of crashing.
    """
    if not isinstance(tag, str):
        return ""
    return tag.split("}")[-1] if "}" in tag else tag


def _clean(text: str | None) -> str:
    """Collapse all whitespace/newlines into single spaces."""
    if not text:
        return ""
    return " ".join(text.split())


def _extract_text_body(tb) -> str:
    """
    Extract the text of a <text_body>.
    Skips <itemize> overview lists, because those summarize the real sections
    and would otherwise create duplicate requirements.
    """
    parts = []
    if tb.text:
        parts.append(_clean(tb.text))
    for el in tb:
        if _strip_ns(el.tag) == "itemize":
            continue  # overview list — real sections carry these requirements
        text = _clean("".join(el.itertext()))
        if text:
            parts.append(text)
        if el.tail:
            parts.append(_clean(el.tail))
    return " ".join(p for p in parts if p)


def _extract_itemize_items(tb) -> list[str]:
    """Return the text of every <item> inside any <itemize> under a <text_body>.

    Used ONLY for "Functional Requirements" sections, where each item (e.g.
    "REQ-1: ...") is a real requirement. Elsewhere itemize is skipped as overview.
    """
    items: list[str] = []
    for el in tb.iter():
        if _strip_ns(el.tag) == "item":
            text = _clean("".join(el.itertext()))
            if text:
                items.append(text)
    return items


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def _parse_node(node, fallback_id: str) -> dict | None:
    """Recursively parse a <p> node into {id, title, body, children}."""
    if _strip_ns(node.tag) != "p":
        return None

    # real id if present, else position-based fallback (handles SRS w/o ids)
    node_id = node.get("id") or fallback_id

    title = ""
    body = ""
    items: list[str] = []
    children = []
    child_index = 0

    for child in node:
        ctag = _strip_ns(child.tag)
        if ctag == "title":
            title = _clean("".join(child.itertext()))
        elif ctag == "text_body":
            body = _extract_text_body(child)
            items = _extract_itemize_items(child)
        elif ctag == "p":
            child_index += 1
            parsed = _parse_node(child, f"{node_id}.{child_index}")
            if parsed:
                children.append(parsed)

    return {"id": node_id, "title": title, "body": body, "items": items, "children": children}


# --------------------------------------------------------------------------
# FR-only, section-aware feature building
# --------------------------------------------------------------------------
FR_SECTION_TITLE = "functional requirements"  # the ONLY section title we extract from

# A leading "REQ-<n>:" label inside an <item>, e.g. "REQ-1: Torrent search will ...".
_REQ_LABEL = re.compile(r"^\s*REQ[-_\s]?(\d+)\s*[:.)\-]?\s*(.*)$", re.IGNORECASE | re.DOTALL)

# Normative RFC 2119 language in PEPPOL-style ``req_document`` itemize bullets.
_NORMATIVE = re.compile(
    r"\b(MUST NOT|SHALL NOT|SHOULD NOT|MUST|SHALL|SHOULD)\b",
    re.IGNORECASE,
)


def _is_fr_section(node: dict) -> bool:
    """True iff this node's title is exactly 'Functional Requirements' (case-insensitive)."""
    return _clean(node.get("title", "")).lower() == FR_SECTION_TITLE


def _parse_req_item(item_text: str) -> tuple[str | None, str]:
    """Split an itemize entry into ('REQ-<n>', body); label is None if no REQ prefix."""
    m = _REQ_LABEL.match(item_text)
    if m:
        return f"REQ-{int(m.group(1))}", _clean(m.group(2))
    return None, _clean(item_text)


def _feature_description(parent: dict) -> str:
    """A feature's blurb: its own text, else its 'Description and Priority' child's text."""
    if parent.get("body"):
        return parent["body"]
    for child in parent.get("children", []):
        if "description" in _clean(child.get("title", "")).lower():
            return child.get("body", "")
    return ""


def build_fr_features(tree: list[dict]) -> list[dict]:
    """Build features from FUNCTIONAL-REQUIREMENT sections only.

    Walk the parsed tree; whenever a node's title is "Functional Requirements", its
    PARENT is the feature and the section's <itemize> items (REQ-N) are that feature's
    requirements. IDs are derived purely from structure: '<feature_id>.REQ-<n>'.
    Narrative and non-functional sections are never visited for extraction.
    """
    features: dict[str, dict] = {}
    order: list[str] = []

    def add_feature(parent: dict, fr_node: dict) -> None:
        feature_id = parent["id"]
        if feature_id not in features:
            features[feature_id] = {
                "id": feature_id,
                "name": parent.get("title") or feature_id,
                "description": _feature_description(parent),
                "functional_requirements": [],
            }
            order.append(feature_id)
        reqs = features[feature_id]["functional_requirements"]

        items = fr_node.get("items", [])
        if items:
            for idx, item in enumerate(items, start=1):
                label, text = _parse_req_item(item)
                req_id = f"{feature_id}.{label or f'REQ-{idx}'}"
                reqs.append({"id": req_id, "text": text})
        else:
            # Fallback for SRS variants that nest FR sub-<p> nodes instead of itemize.
            for child in fr_node.get("children", []):
                text = child.get("body") or child.get("title")
                if text:
                    reqs.append({"id": child["id"], "text": text})
            # Gemini-style: prose requirement(s) directly in the FR section body (no itemize).
            body = _clean(fr_node.get("body", ""))
            if body and not any(r.get("text") == body for r in reqs):
                reqs.append({"id": f"{feature_id}.REQ-{len(reqs) + 1}", "text": body})

    def walk(node: dict) -> None:
        for child in node.get("children", []):
            if _is_fr_section(child):
                add_feature(node, child)
            walk(child)

    for root in tree:
        walk(root)

    return _split_lone_feature([features[k] for k in order])


def _split_lone_feature(features: list[dict]) -> list[dict]:
    """If the document collapsed to a SINGLE feature carrying multiple requirements, split it
    into one feature per requirement.

    A lone multi-requirement feature becomes one oversized Dafny state machine whose proof is
    all-or-nothing — e.g. video search parses to 1 feature ("Torrent Search") holding 7 FRs, and
    weaker models (deepseek/gpt) cannot discharge the whole 7-requirement proof in one shot, so
    its verification rate sits at 0. Splitting gives each requirement its own small proof, the
    1:1 granularity that verifies well elsewhere.

    Deliberately fires ONLY when there is exactly one feature: multi-feature documents
    (dineout, gamma, Human, …) are returned untouched, so their existing grouping/results are
    unaffected. The owning feature name is kept as actor context in ``description``.
    """
    if len(features) != 1:
        return features
    only = features[0]
    reqs = only.get("functional_requirements", [])
    if len(reqs) <= 1:
        return features
    actor = _clean(only.get("name") or only.get("id") or "")
    split: list[dict] = []
    for req in reqs:
        fid = req["id"]
        split.append({
            "id": fid,
            "name": f"{actor}: {fid}" if actor else fid,
            "description": actor,
            "functional_requirements": [{"id": fid, "text": req["text"]}],
        })
    return split


def _is_nfr_section_title(title: str) -> bool:
    """Skip sections that are explicitly non-functional requirement lists."""
    t = _clean(title).lower()
    return "non-functional" in t or "non functional" in t


def _normative_items(node: dict) -> list[str]:
    """Itemize entries that contain RFC 2119 normative keywords."""
    return [item for item in node.get("items", []) if _NORMATIVE.search(item)]


def build_peppol_normative_features(tree: list[dict]) -> list[dict]:
    """Build features from PEPPOL / VCD ``req_document`` SRS variants.

    Each ``<p>`` subsection whose itemize list contains MUST/SHOULD/SHALL bullets
    becomes one feature; each normative bullet becomes ``<feature_id>.REQ-<n>``.
    Used when the document has no explicit "Functional Requirements" sections.
    """
    features: dict[str, dict] = {}
    order: list[str] = []

    def add_feature(node: dict, items: list[str]) -> None:
        feature_id = node["id"]
        if feature_id not in features:
            features[feature_id] = {
                "id": feature_id,
                "name": node.get("title") or feature_id,
                "description": node.get("body", ""),
                "functional_requirements": [],
            }
            order.append(feature_id)
        reqs = features[feature_id]["functional_requirements"]
        for idx, item in enumerate(items, start=len(reqs) + 1):
            label, text = _parse_req_item(item)
            req_id = f"{feature_id}.{label or f'REQ-{idx}'}"
            reqs.append({"id": req_id, "text": text})

    def walk(node: dict) -> None:
        if _is_nfr_section_title(node.get("title", "")):
            for child in node.get("children", []):
                walk(child)
            return
        items = _normative_items(node)
        if items:
            add_feature(node, items)
        for child in node.get("children", []):
            walk(child)

    for root in tree:
        walk(root)

    return [features[k] for k in order if features[k]["functional_requirements"]]


def build_userclass_features(root) -> list[dict]:
    """SRS variant: ``<SRS><FunctionalRequirements>`` grouping ``<UserClass>`` blocks of
    ``<Requirement>`` (e.g. kinmail).

    Example::

        <FunctionalRequirements>
          <UserClass id="1" name="Non Registered Users">
            <Requirement id="4.1.1"><Title>..</Title><Desc>..</Desc></Requirement>

    Each ``<Requirement>`` becomes its OWN feature — id from the ``id`` attribute, name from
    ``<Title>``, text from ``<Desc>`` (falling back to all descendant text), with the owning
    ``<UserClass>`` name kept as actor context in ``description``. This deliberately does NOT
    group by ``<UserClass>``: grouping collapsed kinmail's 13 FRs into 2 giant features, which
    produced oversized single-state-machine Dafny proofs that rarely verified (verification
    rate ~0 for all but top-tier models). One feature per requirement keeps each proof small,
    matching the 1:1 granularity that verifies well for the other SRS. See HANDOFF.md §6.
    """
    fr = root.find(".//FunctionalRequirements")
    if fr is None:
        return []

    features: list[dict] = []
    seen_ids: set[str] = set()
    classes = [c for c in fr if _strip_ns(c.tag) == "UserClass"]
    groups = classes or [fr]
    for grp in groups:
        actor = _clean(grp.get("name") or grp.get("id") or "")
        for req in grp.iter():
            if _strip_ns(req.tag) != "Requirement":
                continue
            desc_el = next((e for e in req if _strip_ns(e.tag) == "Desc"), None)
            title_el = next((e for e in req if _strip_ns(e.tag) == "Title"), None)
            src = desc_el if desc_el is not None else req
            text = _clean("".join(src.itertext()))
            if not text:
                continue

            feature_id = req.get("id") or str(len(features) + 1)
            # Guard against duplicate Requirement ids across UserClass blocks.
            base_id, n = feature_id, 2
            while feature_id in seen_ids:
                feature_id = f"{base_id}-{n}"
                n += 1
            seen_ids.add(feature_id)

            title = _clean("".join(title_el.itertext())) if title_el is not None else ""
            name = title or (f"{actor}: {feature_id}" if actor else feature_id)
            features.append({
                "id": feature_id,
                "name": name,
                "description": actor,
                "functional_requirements": [{"id": feature_id, "text": text}],
            })
    return features


def _is_modules_fr_section(title: str) -> bool:
    """A section whose title CONTAINS 'functional requirements' but is not the non-functional
    list (e.g. 'Description of the Modules and Functional Requirements')."""
    t = _clean(title).lower()
    return "functional requirements" in t and "non-functional" not in t and "non functional" not in t


def build_module_section_features(tree: list[dict]) -> list[dict]:
    """Last-resort ``req_document`` fallback (e.g. cctns).

    Used only when no exact "Functional Requirements" section exists. Finds a section whose
    title CONTAINS "functional requirements" and treats each of its child ``<p>`` nodes as a
    module/feature: the module's prose body becomes ``<id>.REQ-1`` and any nested ``<p>``
    bodies / itemize items become further requirements.
    """
    features: list[dict] = []

    def module_to_feature(mod: dict) -> dict | None:
        reqs: list[dict] = []
        for idx, item in enumerate(mod.get("items", []), start=1):
            label, text = _parse_req_item(item)
            if text:
                reqs.append({"id": f"{mod['id']}.{label or f'REQ-{idx}'}", "text": text})
        body = _clean(mod.get("body", ""))
        if body and not any(r["text"] == body for r in reqs):
            reqs.insert(0, {"id": f"{mod['id']}.REQ-1", "text": body})
        for child in mod.get("children", []):
            ctext = _clean(child.get("body") or child.get("title") or "")
            if ctext:
                reqs.append({"id": child["id"], "text": ctext})
        if not reqs:
            return None
        return {
            "id": mod["id"],
            "name": mod.get("title") or mod["id"],
            "description": body,
            "functional_requirements": reqs,
        }

    seen: set[str] = set()

    def walk(node: dict) -> None:
        # Check the node itself: a modules section can be a top-level root or nested.
        if _is_modules_fr_section(node.get("title", "")):
            for mod in node.get("children", []):
                feat = module_to_feature(mod)
                if feat and feat["id"] not in seen:
                    seen.add(feat["id"])
                    features.append(feat)
        for child in node.get("children", []):
            walk(child)

    for root in tree:
        walk(root)
    return features


def build_system_requirements_features(root) -> list[dict]:
    """Parse SRS variants that declare features directly under ``SystemRequirements``.

    Example (DineOut): ``<Feature id="4.1" name="Place Order"><Description>...</Description></Feature>``.
    Each feature's ``Description`` becomes a single functional requirement (``<id>.REQ-1``).
    Non-functional sections elsewhere in the document are ignored.
    """
    sr = root.find(".//SystemRequirements")
    if sr is None:
        return []

    features: list[dict] = []
    for feat in sr:
        if _strip_ns(feat.tag) != "Feature":
            continue
        feature_id = feat.get("id") or str(len(features) + 1)
        name = feat.get("name") or feature_id
        desc_el = feat.find("Description")
        if desc_el is not None:
            description = _clean("".join(desc_el.itertext()))
        else:
            # Gemini-style: requirement text directly inside <Feature> with no <Description>.
            description = _clean(feat.text or "")

        frs: list[dict] = []
        if description:
            frs.append({"id": f"{feature_id}.REQ-1", "text": description})
        # Nested itemize under the feature (if present) adds further REQ-N entries.
        for idx, item in enumerate(_extract_itemize_items(feat), start=2 if description else 1):
            label, text = _parse_req_item(item)
            frs.append({"id": f"{feature_id}.{label or f'REQ-{idx}'}", "text": text})

        if frs:
            features.append({
                "id": feature_id,
                "name": name,
                "description": description,
                "functional_requirements": frs,
            })
    return features


_TAGGED_PDF_HEADINGS = {"H1", "H2", "H3", "H4", "H5", "H6"}
# A use-case marker: "3.1.<n> <Title>". The PDF export tags SOME use-case titles as <H4>
# headings and leaves OTHERS as plain <P> body text inside the previous section, so we must
# split on this marker wherever it appears — not only on headings.
_TAGGED_PDF_MARKER = re.compile(r"^3\.1\.(\d+)\b\s*(.*)$")
_TAGGED_PDF_STOP = re.compile(r"^3\.2\b")        # start of 3.2 Non-Functional Requirements
_TAGGED_PDF_BLOCKS = {"P", "Lbl", "LBody", "L", "Table", "Figure"}
_MARKER_MAX_LEN = 60                              # a title-only line is short; body prose is long


def _tagged_pdf_heading(sect) -> str:
    for ch in sect:
        if _strip_ns(ch.tag) in _TAGGED_PDF_HEADINGS:
            return _clean("".join(ch.itertext()))
    return ""


def _tagged_pdf_stream(elem, out: list) -> None:
    """Flatten a Sect subtree into an ordered (tag, text) stream. Recurse only into nested
    ``Sect``s; treat lists/tables/figures as opaque text blobs so their inner ``P``/``TD``
    nodes aren't double-counted (and can't masquerade as use-case markers)."""
    for ch in elem:
        n = _strip_ns(ch.tag)
        if n == "Sect":
            _tagged_pdf_stream(ch, out)
        elif n in _TAGGED_PDF_HEADINGS or n in _TAGGED_PDF_BLOCKS:
            out.append((n, _clean("".join(ch.itertext()))))


def _is_usecase_marker(tag: str, text: str):
    """Return (number, title) if this block STARTS a use case, else None. A marker is either a
    heading or a short standalone title line — long body paragraphs that merely mention a
    section number are rejected by the length guard."""
    m = _TAGGED_PDF_MARKER.match(text)
    if not m:
        return None
    if tag in _TAGGED_PDF_HEADINGS or len(text) <= _MARKER_MAX_LEN:
        return m.group(1), m.group(2).strip()
    return None


# --------------------------------------------------------------------------
# Tagged-PDF IEEE-830 SRS: a "System Features" / "Functional Requirements" section
# whose requirements are either per-feature "REQ-N. The system shall ..." paragraphs
# (e.g. Shoten) or a flat bullet list (e.g. G16, the trading SRS). Distinct from the
# use-case branch below, which keys on "3. Specific Requirements" / "3.1.<n>" (foodsaver).
# --------------------------------------------------------------------------
_IEEE_FR_ANCHOR = re.compile(r"system features|functional requirements", re.I)
_IEEE_NONFUNC = re.compile(r"non[\s\-]*functional", re.I)          # exclude "Non-Functional Requirements"
_IEEE_SUBSEC = re.compile(r"^(\d+\.\d+(?:\.\d+)*)(?:\.\s*|\s+)(.+)$")  # "4.1 Title" / "4.1. Title" / "4.12.Title"
_IEEE_REQ = re.compile(r"\bREQ[-\s]?\d+\b\.?\s*", re.I)            # "REQ-1." markers within a body
_IEEE_BULLET_LBL = re.compile(r"^[•●▪◦‣·•·◦‣*\-o]+$")  # pure bullet labels
_IEEE_STOP = re.compile(
    r"non[\s\-]*functional|external interface|use[\s\-]*case|other (?:expected )?requirements?|"
    r"requirement traceability|performance requirements|safety|appendix|business rules|"
    r"references|glossary|design and implementation", re.I)
_IEEE_LEAF = {"H1", "H2", "H3", "H4", "H5", "H6", "P", "LBody", "Lbl", "TD"}

# --- Thin-doc enrichment (flat-bullet IEEE SRS only, e.g. Event Management / trading) ---------
# Some student-template SRS state their real functionality not in one "Functional Requirements"
# bullet list but spread across "Product Functionality", "Functional Requirements" and the
# "User Interfaces" subsections. For the FLAT-LIST shape only (single anchor, no per-feature
# REQ markers) we additionally harvest those sections' bullets. A sticky section-context tracker
# keeps us inside functional sections and out of the non-functional / infrastructure ones.
_IEEE_FUNC_SECTION = re.compile(
    r"product functionality|product features|functional requirement|user interface", re.I)
_IEEE_NONFUNC_SECTION = re.compile(
    r"non[\s\-]*functional|hardware interface|software interface|communication|performance|"
    r"safety|security|quality|operating environment|assumption|dependenc|constraint|"
    r"reference|document|scope|overview|glossary|appendix|traceability|revision|definition|"
    r"user classes", re.I)
_IEEE_SECTION_HDR = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(.{2,80}?)\s*:?\s*$")
_IEEE_BARE_NUM = re.compile(r"^\d+(?:\.\d+)*\.?$")
_IEEE_BULLET_PREFIX = re.compile(r"^\s*[●•▪◦‣·*\-o]\s+")


def _looks_like_bullet(tag: str, text: str) -> bool:
    """A functional bullet is a list-body item, or a paragraph that opens with a bullet glyph."""
    return tag == "LBody" or (tag == "P" and bool(_IEEE_BULLET_PREFIX.match(text)))


def _collect_functional_bullets(root) -> list[str]:
    """Harvest bullet items that sit under functional sections (Product Functionality /
    Functional Requirements / User Interfaces), skipping non-functional and infrastructure
    sections. Used only to enrich the thin flat-list IEEE shape."""
    stream: list[tuple[str, str]] = []
    _ieee_stream(root, stream)
    functional = False
    out: list[str] = []
    prev: tuple[str, str] = ("", "")
    for tag, raw in stream:
        t = _clean(raw)
        if not t:
            prev = (tag, t)
            continue
        # Section header: either a numbered line, or an "Lbl number" + "LBody title" pair
        # (the flat export splits "3.2 Requirement Traceability Matrix" across two leaves).
        title = None
        if prev[0] == "Lbl" and _IEEE_BARE_NUM.match(prev[1]) and tag in ("LBody", "P"):
            title = t
        else:
            m = _IEEE_SECTION_HDR.match(t)
            if m and (tag in _TAGGED_PDF_HEADINGS or len(t) <= 80):
                title = m.group(2)
        if title is not None:
            if _IEEE_NONFUNC_SECTION.search(title):
                functional = False
            elif _IEEE_FUNC_SECTION.search(title):
                functional = True
            # else: neither — keep the current (sticky) state for sub-sections.
            prev = (tag, t)
            continue
        if functional and _looks_like_bullet(tag, t):
            b = _IEEE_BULLET_PREFIX.sub("", t).strip()
            if len(b) >= 12 and not _IEEE_BULLET_LBL.match(b):
                out.append(b)
        prev = (tag, t)
    return out


def _enrich_flat_ieee(root, base: str, primary_texts: list[str]) -> list[dict]:
    """Combine the anchor section's FRs with functional bullets harvested from the rest of the
    document, de-duplicate, and emit one feature per requirement (the small-proof granularity
    that verifies well, matching ``_split_lone_feature``)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for txt in list(primary_texts) + _collect_functional_bullets(root):
        key = re.sub(r"\W+", " ", txt.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(txt)
    feats: list[dict] = []
    for i, txt in enumerate(ordered, 1):
        fid = f"{base}.REQ-{i}"
        feats.append({"id": fid, "name": fid, "description": "",
                      "functional_requirements": [{"id": fid, "text": txt}]})
    return feats


def _ieee_stream(elem, out: list) -> None:
    """Flatten the doc to an ordered (tag, text) stream of text-bearing LEAF blocks.

    Emits each leaf (heading / P / Lbl / LBody / TD) once via itertext() and does NOT recurse
    into it (so a nested P inside an LBody isn't double-counted), while recursing through every
    structural container (Sect, Part, L, LI, Table, …) so individual list bullets survive."""
    for ch in elem:
        n = _strip_ns(ch.tag)
        if n in _IEEE_LEAF:
            t = _clean("".join(ch.itertext()))
            if t:
                out.append((n, t))
        else:
            _ieee_stream(ch, out)


def _ieee_anchor_num(text: str) -> str:
    m = re.match(r"^(\d+(?:\.\d+)*)", text.strip())
    return m.group(1) if m else ""


def _ieee_frs_from_body(fid: str, body: list[tuple[str, str]]) -> list[dict]:
    """Turn one feature's body blocks into functional requirements.

    Priority: explicit ``REQ-N.`` markers (split the joined text on them) → flat bullet
    ``LBody`` items → the whole body as a single requirement. Guarantees every feature with
    any requirement text yields at least one FR."""
    joined = " ".join(t for n, t in body if n in ("P", "LBody", "Lbl", "TD"))
    frs: list[dict] = []
    if _IEEE_REQ.search(joined):
        items = [p.strip() for p in _IEEE_REQ.split(joined)[1:] if p.strip()]
        for j, it in enumerate(items, 1):
            frs.append({"id": f"{fid}.REQ-{j}", "text": _clean(it)})
        if frs:
            return frs
    items = [t for n, t in body if n == "LBody" and t and not _IEEE_BULLET_LBL.match(t)]
    if not items:  # some exports carry list items as plain <P>
        items = [t for n, t in body if n == "P" and len(t) > 15 and not _IEEE_SUBSEC.match(t)]
    items = [it for it in items if _clean(it)]
    if items:
        return [{"id": f"{fid}.REQ-{j}", "text": _clean(it)} for j, it in enumerate(items, 1)]
    if _clean(joined):
        return [{"id": f"{fid}.REQ-1", "text": _clean(joined)}]
    return []


def build_tagged_pdf_ieee_features(root) -> list[dict]:
    """Parse Tagged-PDF IEEE-830 SRS whose FRs live under a "System Features" /
    "Functional Requirements" section (e.g. Shoten, G16, the trading SRS).

    Two sub-shapes, handled uniformly: (a) per-feature subsections ``N.N <Title>`` each with
    ``REQ-N. The system shall …`` paragraphs, and (b) a flat bullet list directly under the
    section. The anchor explicitly EXCLUDES "Non-Functional Requirements", so foodsaver (which
    has no such heading) falls through untouched to the use-case branch."""
    stream: list[tuple[str, str]] = []
    _ieee_stream(root, stream)

    anchor = None
    for i, (n, t) in enumerate(stream):
        if n in _TAGGED_PDF_HEADINGS and _IEEE_FR_ANCHOR.search(t) and not _IEEE_NONFUNC.search(t):
            anchor = i
            break
    if anchor is None:
        return []

    region: list[tuple[str, str]] = []
    for n, t in stream[anchor + 1:]:
        is_markerish = n in _TAGGED_PDF_HEADINGS or len(t) <= 80 or bool(_IEEE_SUBSEC.match(t))
        if is_markerish and _IEEE_STOP.search(t):
            break
        region.append((n, t))

    markers = [
        (i, m.group(1), m.group(2).strip())
        for i, (n, t) in enumerate(region)
        for m in [_IEEE_SUBSEC.match(t)]
        if m and (n in _TAGGED_PDF_HEADINGS or len(t) <= 80)
    ]

    features: list[dict] = []
    if markers:
        bounds = [mi for mi, _, _ in markers] + [len(region)]
        for k, (mi, num, title) in enumerate(markers):
            body = region[mi + 1: bounds[k + 1]]
            frs = _ieee_frs_from_body(num, body)
            if frs:
                features.append({"id": num, "name": title or num,
                                 "description": title, "functional_requirements": frs})
    else:
        num = _ieee_anchor_num(stream[anchor][1]) or "3"
        title = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", stream[anchor][1]).strip() or stream[anchor][1]
        frs = _ieee_frs_from_body(num, region)
        if frs:
            features.append({"id": num, "name": title,
                             "description": stream[anchor][1], "functional_requirements": frs})

    # Thin shape: a single feature means this doc spreads its functionality across several
    # sections (Product Functionality / User Interfaces / …), so enrich the anchor FRs with
    # bullets harvested from those sections, split one-per-feature. Multi-feature docs (Shoten,
    # G16) are returned untouched, so their existing extraction/results are unaffected.
    if len(features) == 1:
        base = features[0]["id"]
        return _enrich_flat_ieee(root, base,
                                 [fr["text"] for fr in features[0]["functional_requirements"]])
    return features


def build_tagged_pdf_usecase_features(root) -> list[dict]:
    """Parse Acrobat "SaveAsXML" Tagged-PDF exports (``<TaggedPDF-doc>``, e.g. foodsaver).

    The logical structure is ``Part > Sect > {H1..H6, P, L/LI, Table}``. Functional use cases
    live under the "3. Specific Requirements" section as ``3.1.<n> <Title>`` blocks. Crucially
    the PDF export is INCONSISTENT: some titles are tagged ``<H4>`` headings, others are plain
    ``<P>`` text embedded in the previous use case's section. So we scope to the Specific
    Requirements subtree (excludes the Table-of-Contents and 3.2 Non-Functional sections),
    flatten it to an ordered block stream, and split on the ``3.1.<n>`` marker wherever it
    appears. Each use case's following body prose (Description / Actor / Trigger / Conditions /
    Exceptions) becomes one functional requirement. Duplicate section numbers (the source has
    two ``3.1.10``s) get a ``_<k>`` suffix so feature ids stay unique.
    """
    # Scope to the "Specific Requirements" section; fall back to the whole doc if not found.
    scope = None
    for sect in root.iter():
        if _strip_ns(sect.tag) == "Sect" and \
                re.match(r"^3\.?\s*\.?\s*Specific Requirements", _tagged_pdf_heading(sect)):
            scope = sect
            break
    stream: list = []
    _tagged_pdf_stream(scope if scope is not None else root, stream)

    feats: list[dict] = []
    seen: dict[str, int] = {}
    cur: dict | None = None
    stopped = False
    for tag, text in stream:
        if not text:
            continue
        if _TAGGED_PDF_STOP.match(text) and (tag in _TAGGED_PDF_HEADINGS or len(text) <= _MARKER_MAX_LEN):
            stopped = True
        if stopped:
            continue
        mk = _is_usecase_marker(tag, text)
        if mk:
            num, title = mk
            base = f"3.1.{num}"
            seen[base] = seen.get(base, 0) + 1
            fid = base if seen[base] == 1 else f"{base}_{seen[base]}"   # disambiguate dup 3.1.10
            cur = {"id": fid, "name": title or fid, "_body": []}
            feats.append(cur)
        elif cur is not None:
            cur["_body"].append(text)

    out: list[dict] = []
    for f in feats:
        description = " ".join(f.pop("_body")).strip() or f["name"]
        out.append({
            "id": f["id"],
            "name": f["name"],
            "description": description,
            "functional_requirements": [{"id": f"{f['id']}.REQ-1", "text": description}],
        })
    return out


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------
class SRSReader:
    def read_tree(self, path: Path) -> list[dict]:
        """Full nested tree of the document."""
        if not path.exists():
            raise FileNotFoundError(f"SRS file not found: {path}")
        tree = etree.parse(str(path))
        root = tree.getroot()

        sections = []
        idx = 0
        for child in root:
            if _strip_ns(child.tag) == "p":
                idx += 1
                parsed = _parse_node(child, str(idx))
                if parsed:
                    sections.append(parsed)
        return sections

    def read_features(self, path: Path) -> list[dict]:
        """Functional requirements grouped into features (FR-only, section-aware).

        Supports three deterministic SRS shapes:
          1. Legacy ``req_document`` with nested ``<p>`` nodes and a "Functional Requirements"
             section per feature (itemize items become REQ-N).
          2. ``SystemRequirements`` / ``<Feature>`` lists (e.g. DineOut) where each feature's
             ``Description`` (or inline body text) becomes ``<feature_id>.REQ-1``.
          3. PEPPOL / VCD ``req_document`` with normative MUST/SHOULD/SHALL itemize bullets
             under requirement subsections (each subsection becomes a feature).
        """
        if not path.exists():
            raise FileNotFoundError(f"SRS file not found: {path}")
        doc = etree.parse(str(path))
        root = doc.getroot()
        tree = self.read_tree(path)

        features = build_fr_features(tree)
        if features:
            return features
        features = build_system_requirements_features(root)
        if features:
            return features
        # <SRS><FunctionalRequirements><UserClass><Requirement> (e.g. kinmail).
        features = build_userclass_features(root)
        if features:
            return features
        features = build_peppol_normative_features(tree)
        if features:
            return features
        # Tagged-PDF IEEE-830 SRS with a "System Features"/"Functional Requirements" section
        # (e.g. Shoten, G16, trading SRS). Runs BEFORE the use-case branch because that branch's
        # "3.1.<n>" marker would otherwise mis-grab these docs' "3.1.x External Interface" items.
        # The anchor excludes "Non-Functional", so foodsaver returns [] here and falls through.
        features = build_tagged_pdf_ieee_features(root)
        if features:
            return features
        # Acrobat "SaveAsXML" Tagged-PDF exports (<TaggedPDF-doc>, e.g. foodsaver): 3.1.x
        # use-case sections become features. Additive — only reached when none above matched.
        features = build_tagged_pdf_usecase_features(root)
        if features:
            return features
        # Last resort: a "… Modules and Functional Requirements" section of prose modules
        # (e.g. cctns). Only reached when nothing above matched, so working SRS are untouched.
        return build_module_section_features(tree)


if __name__ == "__main__":
    import sys

    reader = SRSReader()
    path = Path(sys.argv[1])
    feats = reader.read_features(path)
    total = sum(len(f["functional_requirements"]) for f in feats)
    print(f"{path.name}: {len(feats)} features, {total} requirements\n")
    for f in feats:
        print(f"[{f['id']}] {f['name']} -> {len(f['functional_requirements'])} reqs")