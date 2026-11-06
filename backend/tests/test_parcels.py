"""Address parsing and county parcel conversion (no network)."""

from tr_api.parcels import PROVIDERS, _parse_address


def test_parse_address():
    assert _parse_address("700 Freestone Ranch Road, Sebastopol CA 95472") == ("700", "FREESTONE RANCH")
    assert _parse_address("12 Main St") == ("12", "MAIN")
    assert _parse_address("Freestone Ranch Rd") is None


def test_sonoma_parcel_conversion():
    sonoma = PROVIDERS[0]
    assert sonoma.covers(-122.906, 38.350) and not sonoma.covers(-121.0, 38.35)
    feat = {
        "type": "Feature",
        "geometry": {"type": "MultiPolygon", "coordinates": [
            [[[-122.91, 38.35], [-122.90, 38.35], [-122.90, 38.36], [-122.91, 38.36], [-122.91, 38.35]]],
            [[[-122.80, 38.30], [-122.801, 38.30], [-122.801, 38.301], [-122.80, 38.30]]],
        ]},
        "properties": {"APN": "026-090-027", "SitusFormatted1": "700 FREESTONE RANCH RD", "SitusCity": "SEBASTOPOL", "LandSizeAcres": 377.08},
    }
    p = sonoma.to_parcel(feat)
    assert p["apn"] == "026-090-027" and p["acres"] == 377.08
    assert p["address"] == "700 Freestone Ranch Rd, Sebastopol"
    assert p["boundary"]["type"] == "Polygon" and len(p["boundary"]["coordinates"][0]) == 5
