"""Knowledge base: chunking, NRCS page parsing, DwC-A species import, rules, and hybrid search."""

import io
import os
import tarfile

import pytest

from tr_kb import chunking, nrcs, plants, rules

INDEX_HTML = """
<ul>
<li><a href="/resources/guides-and-instructions/access-road-ft-560-conservation-practice-standard">Access Road (Ft.) (560) 09/2020</a></li>
<li><a href="https://www.nrcs.usda.gov/resources/guides-and-instructions/annual-forages-for-grazing-systems-ac513-conservation-practice">Annual Forages for Grazing Systems (Ac.)(513)(11/2026)</a></li>
<li><a href="/resources/guides-and-instructions/pond-no-378-conservation-practice-standard">Pond (No.) (378) 07/2022</a></li>
<li><a href="/about">About NRCS</a></li>
</ul>"""

PRACTICE_HTML = """
<a href="/sites/default/files/2022-09/Pond_378_NHCP_CPS_2022.pdf">Pond (No.) (378) (7/2022) Standard Document</a>
<a href="/sites/default/files/2022-09/Pond_378_NHCP_PO_2022.pdf">Pond (No.) (378) Overview</a>
<a href="/sites/default/files/2022-09/Pond_378_CPPE.pdf">Pond (No.) (378) CPPE</a>"""

CPS_TEXT = """Natural Resources Conservation Service
CONSERVATION PRACTICE STANDARD
POND
CODE 378
DEFINITION
A water impoundment made by constructing an embankment or by excavating a pit or dugout.
PURPOSE
This practice may be applied to provide water for livestock, fish and wildlife, recreation, fire control.
CONDITIONS WHERE PRACTICE APPLIES
This practice applies to sites where the drainage area is adequate and soils are suitable.
CRITERIA
Embankment ponds shall have an auxiliary spillway. """ + ("Design storm and spillway capacity shall meet the criteria in Table 1. " * 40)


def test_parse_index_and_practice_page():
    ps = nrcs.parse_index(INDEX_HTML)
    assert [p.code for p in ps] == ["560", "513", "378"]
    pond = ps[2]
    assert pond.name == "Pond" and pond.unit == "No." and pond.version == "07/2022"
    assert pond.url.startswith("https://www.nrcs.usda.gov/resources/")
    pdfs = nrcs.parse_practice_pdfs(PRACTICE_HTML, pond.url)
    assert pdfs["standard"].endswith("Pond_378_NHCP_CPS_2022.pdf") and pdfs["overview"].endswith("_PO_2022.pdf")


def test_chunks_keep_sections():
    chunks = chunking.chunk(CPS_TEXT, max_chars=600)
    heads = [h for h, _ in chunks]
    assert "Definition" in heads and "Criteria" in heads
    assert all(len(b) <= 700 for _, b in chunks)
    assert sum(1 for h in heads if h == "Criteria") >= 3


def _dwca() -> bytes:
    meta = """<archive xmlns="http://rs.tdwg.org/dwc/text/">
  <core rowType="http://rs.tdwg.org/dwc/terms/Taxon" fieldsTerminatedBy="\\t" ignoreHeaderLines="1">
    <files><location>taxon.tab</location></files>
    <id index="0"/>
    <field index="0" term="http://rs.tdwg.org/dwc/terms/taxonID"/>
    <field index="1" term="http://rs.tdwg.org/dwc/terms/scientificName"/>
    <field index="2" term="http://rs.tdwg.org/dwc/terms/vernacularName"/>
    <field index="3" term="http://rs.tdwg.org/dwc/terms/family"/>
  </core>
  <extension rowType="http://rs.tdwg.org/dwc/terms/MeasurementOrFact" fieldsTerminatedBy="\\t" ignoreHeaderLines="1">
    <files><location>measurement_or_fact.tab</location></files>
    <coreid index="0"/>
    <field index="0" term="http://rs.tdwg.org/dwc/terms/taxonID"/>
    <field index="1" term="http://rs.tdwg.org/dwc/terms/measurementType"/>
    <field index="2" term="http://rs.tdwg.org/dwc/terms/measurementValue"/>
  </extension>
</archive>"""
    taxon = "taxonID\tscientificName\tvernacularName\tfamily\nQUAG\tQuercus agrifolia Née\tcoast live oak\tFagaceae\nCECO\tCeanothus cordulatus\twhitethorn\tRhamnaceae\n"
    mof = ("taxonID\tmeasurementType\tmeasurementValue\n"
           "QUAG\thttp://example.org/GrowthHabit\tTree\nQUAG\tDrought Tolerance\tHigh\n"
           "CECO\tNitrogen Fixation\tHigh\nCECO\tTemperature, Minimum\t-13\n")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, content in (("meta.xml", meta), ("taxon.tab", taxon), ("measurement_or_fact.tab", mof)):
            data = content.encode()
            info = tarfile.TarInfo(f"usda/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_parse_dwca():
    rows = {r["symbol"]: r for r in plants.parse_dwca(_dwca())}
    assert rows["QUAG"]["common_name"] == "coast live oak"
    assert rows["QUAG"]["traits"] == {"growth_habit": "Tree", "drought_tolerance": "High"}
    assert rows["CECO"]["traits"]["nitrogen_fixation"] == "High" and rows["CECO"]["traits"]["min_temp_f"] == "-13"


def test_rules_load():
    docs = rules.rule_documents()
    ids = {d["code"] for d in docs}
    assert {"keyline-grade", "swale-level", "data-grade", "keypoint"} <= ids
    assert all(d["commercial_ok"] and "Sources:" in d["body"] for d in docs)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_store_and_search(client):
    os.environ["EMBEDDINGS"] = "hash"
    from tr_api.db import get_engine
    from tr_kb import embeddings, store

    embeddings.get_embedder.cache_clear()
    with get_engine().begin() as conn:
        store.upsert_document(conn, source="nrcs_cps", doc_key="nrcs_cps:378:standard", title="NRCS 378 Pond", code="378",
                              url="https://example.org/378.pdf", body=CPS_TEXT, license=nrcs.LICENSE, commercial_ok=True)
        store.upsert_document(conn, source="nrcs_cps", doc_key="test:nc", title="Non-commercial thing", body="Pond spillway " * 30,
                              license="CC BY-NC", commercial_ok=False)
        for d in rules.rule_documents():
            store.upsert_document(conn, **d)
        store.upsert_species(conn, plants.parse_dwca(_dwca()), plants.SOURCE, plants.LICENSE)
    with get_engine().connect() as conn:
        hits = store.search(conn, "auxiliary spillway for an embankment pond")
        assert "378" in [h["code"] for h in hits[:2]]
        assert all(h["title"] != "Non-commercial thing" for h in hits)
        rule_hits = store.search(conn, "how steep should the keyline fall toward the ridges", source="rules")
        assert "keyline-grade" in [h["code"] for h in rule_hits[:2]]
        assert [r["symbol"] for r in store.find_species(conn, nitrogen_fixing=True)] == ["CECO"]
        assert [r["symbol"] for r in store.find_species(conn, "oak")] == ["QUAG"]
        assert [r["symbol"] for r in store.find_species(conn, min_temp_f_at_most=0)] == ["CECO"]
    r = client.get("/api/knowledge/search", params={"q": "pond spillway"})
    assert r.status_code == 200 and "378" in [h["code"] for h in r.json()[:3]]
    assert any(x["id"] == "swale-level" for x in client.get("/api/knowledge/rules").json())
    assert client.get("/api/species", params={"q": "oak"}).json()[0]["symbol"] == "QUAG"


def test_chunks_never_exceed_limit_even_for_tables():
    table = "DEFINITION\n" + " ".join(f"cell{i} 12.5 ft" for i in range(2000))
    for _, body in chunking.chunk(table, max_chars=1400, overlap=150):
        assert len(body) <= 1400


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not set")
def test_search_without_words_is_empty_not_an_error(client):
    for q in ("??", "a é"):
        r = client.get("/api/knowledge/search", params={"q": q})
        assert r.status_code == 200
