"""Downhill data from ChronoRace without live timing (docs/todo.md, Data): result PDFs read into the
downloader's tables (`mtb_dh download --pdf-results`), and slug probing (`--probe`). The PDF text below is
`pdftotext -layout` output in ChronoRace's 2021 and 2025 layouts, names changed; checked against the live
PDFs on 2026-09-28 (2021 Snowshoe: every finish and first split equals the live-timing JSON)."""

import pytest

from racinglines.sources.chronorace import download as D
from racinglines.sources.chronorace import pdf
from racinglines.sources.chronorace.parse import parse_markdown_tables_file

RESULTS = """\
SAT 12 JUN 2021                                                                                                          DOWNHILL FINAL
Start Time: 13:30                                                                                                              Men Elite

                                                     Individual Results


 Rank       Nr Name / UCI MTB Team                    UCI ID        NAT YOB        Speed            I1 / I2         I3 / I4     Time Points
     1. P     6 RIDER Alpha                           10007307417   AUS   1993   48.943 (38)    0:47.441 (9)    2:02.350 (2)   3:26.019     200
                CANYON COLLECTIVE FACTORY TEAM                                                  1:23.759 (4)    2:52.219 (1)     +0.000
     2. P     5 RIDER Bravo                           10072798480   FRA   2001   48.214 (52)    0:46.704 (1)    2:01.097 (1)   3:27.254     160
                COMMENCAL/MUC-OFF BY RIDING                                                     1:21.815 (1)    2:52.923 (3)     +1.235
    56.       99 RIDER Charlie                          10056657377   FRA   2002     51.185 (3)   0:50.994 (60)   2:10.852 (59)   3:48.306      5
                                                                                                  1:31.011 (59)   3:09.569 (57)   +22.287
          P     4 RIDER Delta                           10008723112   FRA   1996   33.645 (61)    1:22.193 (61)   4:27.207 (61)       DNF       -
                  TREK FACTORY RACING DH                                                          2:31.448 (61)   7:24.474 (61)


Entries / Nations Finished          DNF     DSQ      DNS                Weather                   Temperature Distance              Average
     61 / 16         60              1       0        0               Mostly Sunny                   23°C     2.174km              37.989km/h
"""

TT_2021 = """\
THU 2 SEP 2021                                                                                                               DOWNHILL TIMED TRAINING
Start time: 15:30                                                                                                                            Men Elite

                                                              Individual Results


                                                                      RUN 1                          RUN 2                             RUN 3                  Best
 Rank Nr Name / UCI MTB Team                        NAT     Speed      Splits      Time     Speed     Splits        Time      Speed      Splits     Time        Time
    1.    4 RIDER Delta                             FRA      76.190   0:47.363   2:52.309   74.227    0:47.233   17:14.968                    -                2:52.309
            TREK FACTORY RACING DH                                    1:21.130                        8:56.145                                -                  +0.000
                                                                      1:55.949                       14:49.897                                -
                                                                      2:30.314                       16:51.399                                -
    2.   20 RIDER Echo                              FRA      70.358   0:48.752   4:30.053   74.740    0:47.048    2:56.622    77.419   0:46.674   2:53.612     2:53.612
            COMMENCAL/MUC-OFF BY RIDING ADDICTION                     2:38.859                        1:22.233                         1:21.258                  +1.303
                                                                      3:22.947                        1:58.294                         1:56.647
                                                                      4:01.187                        2:34.799                         2:31.765
   19.   11 RIDER Foxtrot                           FRA      73.720   0:48.342   2:58.116   72.727    0:49.586    7:52.849                    -                2:58.116
            GIANT FACTORY OFF - ROAD TEAM                             1:22.152                        4:31.225                                -                  +5.807
                                                                      1:58.447                        6:04.110                                -
                                                                      2:34.793                        7:21.033                                -
         28 RIDER Golf                        IRL                2:57.923                                -                                 -
            CONTINENTAL - NUKEPROOF RACING                      11:45.628                                -                                 -
                                                                        -                                -                                 -
"""

TT_2025 = """\
                                                                Individual Results
                                                 RUN 1                    RUN 2                    RUN 3                    RUN 4                     RUN 5               Best
 Rank Nr Name / UCI MTB Team                  Splits       Time        Splits       Time        Splits       Time        Splits       Time        Splits       Time         Time
    1.    3 RIDER Hotel (FRA)               0:45.530     5:34.422    0:44.302     8:11.315    1:51.979     4:57.054    0:43.980     3:45.605           -                  3:45.605
            COMMENCAL/MUC-OFF BY RIDING     2:32.467   56.466kmh     1:44.376   60.268kmh     2:52.213   58.148kmh     1:43.326   59.103kmh            -                    +0.000
            ADDICTION                       3:18.680                 2:30.672                 3:38.463                 2:28.603                        -
                                            4:45.193                 7:31.313                 4:15.899                 3:05.073                        -
"""


@pytest.mark.quick
def test_results_layout():
    rows = pdf.parse(RESULTS)
    assert [r["name"] for r in rows] == ["RIDER Alpha", "RIDER Bravo", "RIDER Charlie", "RIDER Delta"]
    a = rows[0]
    assert (a["pos"], a["bib"], a["uci_id"], a["nation"], a["team"]) == ("1", "6", "10007307417", "AUS",
                                                                           "CANYON COLLECTIVE FACTORY TEAM")
    assert a["splits"] == ["0:47.441", "1:23.759", "2:02.350", "2:52.219"]      # I1, I2, I3, I4
    assert (a["time"], a["status"]) == ("3:26.019", "")
    assert rows[2]["team"] == "" and rows[2]["gap"] == "+22.287"               # no team: the gap line only
    d = rows[3]
    assert (d["pos"], d["time"], d["status"], d["team"]) == ("", "", "DNF", "TREK FACTORY RACING DH")
    assert pdf.weather(RESULTS) == "Mostly Sunny, 23°C, 2.174km"


@pytest.mark.quick
def test_timed_training_keeps_the_best_run():
    rows = pdf.parse(TT_2021)
    by = {r["name"]: r for r in rows}
    assert by["RIDER Delta"]["splits"] == ["0:47.363", "1:21.130", "1:55.949", "2:30.314"]      # run 1
    assert by["RIDER Echo"]["splits"] == ["0:46.674", "1:21.258", "1:56.647", "2:31.765"]       # run 3, beside Best
    assert by["RIDER Echo"]["team"] == "COMMENCAL/MUC-OFF BY RIDING ADDICTION" and by["RIDER Echo"]["gap"] == "+1.303"
    f = by["RIDER Foxtrot"]                  # the "-" in the team name isn't a missing split
    assert f["splits"] == ["0:48.342", "1:22.152", "1:58.447", "2:34.793"] and f["time"] == "2:58.116"
    g = by["RIDER Golf"]
    assert (g["pos"], g["time"], g["status"], g["splits"]) == ("", "", "DNF", [])
    assert pdf.weather(TT_2021) is None and all(r["uci_id"] == "" for r in rows)


@pytest.mark.quick
def test_timed_training_2025_layout():
    (h,) = pdf.parse(TT_2025)               # five runs, no speed column, the nation in brackets
    assert (h["name"], h["nation"], h["time"]) == ("RIDER Hotel", "FRA", "3:45.605")
    assert h["splits"] == ["0:43.980", "1:43.326", "2:28.603", "3:05.073"]                      # run 4
    assert h["team"] == "COMMENCAL/MUC-OFF BY RIDING ADDICTION"                                  # wrapped


@pytest.mark.quick
def test_pdf_rounds_parse_like_live_timing(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "pdf_text", lambda data: RESULTS if b"final" in data else TT_2021)

    class Resp:
        status_code = 200

        def __init__(self, url):
            self.content = b"%PDF-" + (b"final" if "_f.pdf" in url else b"tt")
    monkeypatch.setattr(D.http, "get", lambda session, url, **kw: Resp(url))
    final = D.fetch_pdf_round({"Start List": "https://x/leog_dhi_me_startlist_f.pdf",
                               "Individual Results": "https://x/leog_dhi_me_results_f.pdf"}, "Final", None)
    tt = D.fetch_pdf_round({"Results": "https://x/leog_dhi_me_results_tt_z.pdf"}, "Timed Training", None)
    f = tmp_path / "20210612_dh_dhi_elite-men.md"
    f.write_text("# WORLD CUP - DHI #1 - Leogang, June 11th-13th 2021, AUT\n\nCategory: Men Elite\n\n"
                 "Source: ChronoRace (prod.chronorace.be), event slug `20210612_dh`\n\n" + tt + "\n" + final)
    rows = parse_markdown_tables_file(f)
    fin = {(r["round"], r["rider_name"]): r for r in rows if r["sector_id"] == "FINISH"}
    assert fin[("final", "RIDER Alpha")]["cum_time_s"] == pytest.approx(206.019)
    assert fin[("final", "RIDER Alpha")]["uci_id"] == "10007307417"
    assert fin[("final", "RIDER Delta")]["status"] == "DNF"
    assert fin[("practice", "RIDER Echo")]["cum_time_s"] == pytest.approx(173.612)
    s = [r for r in rows if r["round"] == "final" and r["rider_name"] == "RIDER Alpha" and r["sector_id"] != "FINISH"]
    assert [r["cum_time_s"] for r in s] == pytest.approx([47.441, 83.759, 122.350, 172.219])


@pytest.mark.quick
def test_missing_pdf_falls_back_to_links(monkeypatch):
    class Resp:
        status_code = 404
        content = b"<?xml version=\"1.0\"?><Error><Code>BlobNotFound</Code></Error>"
    monkeypatch.setattr(D.http, "get", lambda session, url, **kw: Resp())
    assert D.fetch_pdf_round({"Individual Results": "https://x/leog_dhi_me_results_qr_w.pdf"}, "Qualification", None) is None


@pytest.mark.quick
def test_probe_finds_slugs_with_the_discipline(monkeypatch):
    from datetime import date
    trees = {"20210914_dh": dict(DisplayName="DHI #5 - Snowshoe", Childs=[dict(Id="DHI")]),
             "20210915_xco": dict(DisplayName="XCO only", Childs=[dict(Id="XCO")])}

    class Resp:
        status_code = 200

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data
    seen = []

    def get(session, url, **kw):
        slug = url.rsplit("/", 1)[1]
        seen.append(slug)
        return Resp(trees.get(slug))                  # ChronoRace answers null for unknown slugs
    monkeypatch.setattr(D.http, "get", get)
    found = D.probe_event_slugs(date(2021, 9, 14), date(2021, 9, 15), "DHI", None, echo=lambda *a: None)
    assert found == ["20210914_dh"]
    assert seen == [f"2021091{d}_{s}" for d in (4, 5) for s in D.PROBE_SUFFIXES]
