"""Load the in-house design rules library (YAML) as knowledge-base documents."""

from __future__ import annotations

from importlib import resources

import yaml

LICENSE = "Terraform Robotics design rules (proprietary)"


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
                     "sources": r.get("sources", [])},
        })
    return docs
