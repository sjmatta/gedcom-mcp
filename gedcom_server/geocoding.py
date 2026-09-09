"""Conservative local geocoding: never discard supplied jurisdictions."""

from functools import lru_cache

from .helpers import _get_geonames_cache, normalize_place_string, parse_place_components


@lru_cache(maxsize=1)
def _indexes():
    gc = _get_geonames_cache()
    cities: dict[str, list[dict]] = {}
    for city in gc.get_cities().values():
        cities.setdefault(city["name"].casefold(), []).append(city)
    countries = {}
    for iso, country in gc.get_countries().items():
        for name in (iso, country["name"], country.get("iso3", "")):
            if name:
                countries[name.casefold()] = iso
    countries.update({"usa": "US", "u.s.a.": "US", "uk": "GB", "england": "GB"})
    states = {}
    for code, region in gc.get_us_states().items():
        states[code.casefold()] = code
        states[region["name"].casefold()] = code
    return cities, countries, states


def local_geocode(query: str) -> tuple[tuple[float, float] | None, str]:
    """Resolve only a unique exact city with all supplied context verified.

    The local database has country and US state codes, but no county hierarchy.
    Unsupported jurisdictions and ambiguous cities must use a fuller provider
    or remain unresolved. A bare city name is insufficient even if only one
    match happens to exist in this database of larger cities.
    """
    parts = parse_place_components(normalize_place_string(query))
    if len(parts) < 2:
        return None, "low"
    cities, countries, states = _indexes()
    country = countries.get(parts[-1])
    region = None
    if country:
        context = parts[1:-1]
        if context:
            if country != "US" or len(context) != 1 or context[0] not in states:
                return None, "low"
            region = states[context[0]]
    elif len(parts) == 2 and parts[-1] in states:
        country, region = "US", states[parts[-1]]
    else:
        return None, "low"
    matches = [
        city
        for city in cities.get(parts[0], [])
        if city["countrycode"] == country and (region is None or city["admin1code"] == region)
    ]
    if len(matches) != 1:
        return None, "low"
    city = matches[0]
    return (city["latitude"], city["longitude"]), "high"
