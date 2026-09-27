"""
Reference data: the sports, leagues, competitions and categories the project
knows about, plus canonical venue names. `racinglines db seed` (and every
ingest) upserts these, so adding a new sport or league starts here.
"""

SPORTS = {
    # code: (name, result_kind)
    "mtb_dh": ("Mountain bike downhill", "time"),
    "f1": ("Formula 1", "position"),
}

LEAGUES = {
    # code: (name, organizer)
    "uci_mtb": ("UCI Mountain Bike World Series / World Cup", "UCI"),
    "fia_f1": ("FIA Formula One World Championship", "FIA / Formula One Group"),
}

COMPETITIONS = {
    # code: league, sport, name, categories {code: (name, gender, age_group)}
    "uci_dhi_wc": dict(
        league="uci_mtb",
        sport="mtb_dh",
        name="UCI Downhill World Cup",
        categories={
            "ME": ("Men Elite", "M", "elite"),
            "WE": ("Women Elite", "W", "elite"),
            "MJ": ("Men Junior", "M", "junior"),
            "WJ": ("Women Junior", "W", "junior"),
        },
    ),
    "f1_wdc": dict(
        league="fia_f1",
        sport="f1",
        name="Formula 1 World Championship (Drivers)",
        categories={"DRV": ("Drivers", "X", "elite")},
    ),
}

# F1 circuits (FastF1 "Location" slug) that run on public roads: slower, walls, fewer overtakes
STREET_CIRCUITS = {"monte-carlo", "monaco", "baku", "marina-bay", "singapore", "jeddah", "las-vegas", "miami",
                   "miami-gardens", "melbourne", "montreal", "madrid"}

# canonical venue slug: (display name, country)
VENUES = {
    "bielsko-biala": ("Bielsko-Biała", "POL"),
    "fort-william": ("Fort William", "GBR"),
    "la-thuile": ("La Thuile", "ITA"),
    "lake-placid": ("Lake Placid", "USA"),
    "lenzerheide": ("Lenzerheide", "SUI"),
    "leogang": ("Leogang", "AUT"),
    "les-gets": ("Les Gets", "FRA"),
    "loudenvielle": ("Loudenvielle", "FRA"),
    "lourdes": ("Lourdes", "FRA"),
    "maribor": ("Maribor", "SLO"),
    "mona-yongpyong": ("Mona Yongpyong", "KOR"),
    "mont-sainte-anne": ("Mont-Sainte-Anne", "CAN"),
    "pal-arinsal": ("Pal Arinsal (Vallnord)", "AND"),
    "snowshoe": ("Snowshoe", "USA"),
    "val-di-sole": ("Val di Sole", "ITA"),
}

# other spellings seen in source data -> canonical slug
VENUE_ALIASES = {
    "mont-ste-anne": "mont-sainte-anne",
    "vallnord": "pal-arinsal",
    "vallnord-pal-arinsal": "pal-arinsal",
}

# source-data round labels -> running order within a race
ROUND_ORDER = {"practice": 0, "seeding": 1, "qual": 2, "qual1": 2, "qual2": 3, "semi": 4, "final": 5}
