"""Load the in-house design rules library (YAML) as knowledge-base documents."""

from __future__ import annotations

from importlib import resources

import yaml

LICENSE = "Terraform Robotics design rules (proprietary)"
REF_LICENSE = "Catalog description by Terraform Robotics; the linked work is not stored (see work_license)"

# Design-rule `applies_to` -> PINA topics (topics.yaml).
APPLIES_TOPICS = {
    "keyline": ["water", "earthworks", "broad_scale"], "rip": ["water", "soils", "broad_scale"],
    "swale": ["water", "earthworks"], "pond": ["water", "earthworks", "aquaculture"],
    "data": ["design_methods"], "terrain": ["design_methods", "patterns"], "setback": ["design_methods", "built_environment"],
}


def _yaml(name: str) -> dict:
    return yaml.safe_load(resources.files("tr_kb").joinpath(f"rules/{name}").read_text())


def load_topics() -> dict[str, str]:
    return dict(_yaml("topics.yaml")["topics"])


def load_references() -> tuple[str, list[dict]]:
    data = _yaml("references.yaml")
    return str(data.get("version", "0")), data["references"]


def reference_documents() -> list[dict]:
    """Further-reading entries: our own summary of each outside work, stored link-only."""
    version, refs = load_references()
    topics = load_topics()
    docs = []
    for r in refs:
        names = ", ".join(topics[t] for t in r.get("topics", []))
        body = (f"{r['summary'].strip()}\n\nType: {r['kind']}. Author: {r.get('author', 'unknown')}. "
                f"License of the work: {r['work_license']}. Link only: the work itself is not stored or quoted."
                + (f"\n\nTopics: {names}." if names else ""))
        docs.append({
            "source": "references", "doc_key": f"references:{r['id']}", "title": r["title"], "code": None,
            "url": r.get("url"), "body": body, "license": REF_LICENSE, "commercial_ok": True, "version": version,
            "meta": {"link_only": True, "work_license": r["work_license"], "kind": r["kind"], "author": r.get("author"),
                     "stages": r.get("stages", []), "topics": r.get("topics", []), "alt_urls": r.get("alt_urls", [])},
        })
    return docs


def load_rules() -> tuple[str, list[dict]]:
    text = resources.files("tr_kb").joinpath("rules/design_rules.yaml").read_text()
    data = yaml.safe_load(text)
    return str(data.get("version", "0")), data["rules"]


def rule_documents() -> list[dict]:
    version, rules = load_rules()
    docs = []
    for r in rules:
        sources = "\n".join(f"- {s}" for s in r.get("sources", []))
        params = ", ".join(f"{k} = {v}" for k, v in (r.get("parameters") or {}).items())
        body = f"{r['statement'].strip()}\n\n" + (f"Parameters: {params}\n\n" if params else "") + f"Sources:\n{sources}"
        docs.append({
            "source": "rules", "doc_key": f"rules:{r['id']}", "title": r["title"], "code": r["id"], "body": body,
            "license": LICENSE, "commercial_ok": True, "version": version,
            "meta": {"status": r.get("status"), "applies_to": r.get("applies_to", []), "parameters": r.get("parameters", {}),
                     "sources": r.get("sources", []),
                     "topics": sorted({t for a in r.get("applies_to", []) for t in APPLIES_TOPICS.get(a, [])})},
        })
    return docs
