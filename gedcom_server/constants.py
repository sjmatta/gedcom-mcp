"""Constants for GEDCOM parsing and place normalization."""

# Event tags to parse from individuals
EVENT_TAGS = ["BIRT", "DEAT", "RESI", "OCCU", "EVEN", "IMMI", "CENS", "NATU"]

# Place normalization - common abbreviations
PLACE_ABBREVIATIONS = {
    "st.": "saint",
    "st ": "saint ",
    "co.": "county",
    "co ": "county ",
    "mt.": "mount",
    "mt ": "mount ",
    "ft.": "fort",
    "ft ": "fort ",
    "n.y.": "new york",
    "n.y": "new york",
    "nyc": "new york city",
    "l.a.": "los angeles",
    "d.c.": "district of columbia",
    "u.s.a.": "united states",
    "usa": "united states",
    "u.s.": "united states",
    "u.k.": "united kingdom",
    "uk": "united kingdom",
}

# Historical place name mappings (bidirectional)
HISTORICAL_NAMES = {
    # Cities that have been renamed
    "constantinople": "istanbul",
    "kristiania": "oslo",
    "petrograd": "saint petersburg",
    "leningrad": "saint petersburg",
    "saigon": "ho chi minh city",
    "bombay": "mumbai",
    "madras": "chennai",
    "calcutta": "kolkata",
    "peking": "beijing",
    "canton": "guangzhou",
    "rangoon": "yangon",
    "batavia": "jakarta",
    "danzig": "gdansk",
    "breslau": "wroclaw",
    "konigsberg": "kaliningrad",
    "lemberg": "lviv",
    # Countries/Regions
    "prussia": "germany",
    "bohemia": "czech republic",
    "moravia": "czech republic",
    "austro-hungary": "austria",
    "yugoslavia": "serbia",
    "czechoslovakia": "czech republic",
    "ussr": "russia",
    "soviet union": "russia",
    "rhodesia": "zimbabwe",
    "burma": "myanmar",
    "ceylon": "sri lanka",
    "persia": "iran",
    "siam": "thailand",
    "formosa": "taiwan",
    "east germany": "germany",
    "west germany": "germany",
}

# Build reverse mapping for bidirectional search
HISTORICAL_MAPPINGS: dict[str, list[str]] = {}
for old_name, new_name in HISTORICAL_NAMES.items():
    # old -> new
    if old_name not in HISTORICAL_MAPPINGS:
        HISTORICAL_MAPPINGS[old_name] = []
    HISTORICAL_MAPPINGS[old_name].append(new_name)
    # new -> old (for reverse lookup)
    if new_name not in HISTORICAL_MAPPINGS:
        HISTORICAL_MAPPINGS[new_name] = []
    HISTORICAL_MAPPINGS[new_name].append(old_name)
