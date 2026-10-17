from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest

from app.flows.sources import files as f


def test_csv_semicolon_latin1():
    data = "nom;ville\nJosé;Orléans\n".encode("latin-1")
    p = f.parse_file("a.csv", data, cap_bytes=10**6, max_rows=100)
    assert list(p.frame.columns) == ["nom", "ville"] and p.frame.iloc[0, 0] == "José"


def test_csv_tab_and_cap():
    p = f.parse_file("a.csv", b"a\tb\n1\t2\n3\t4\n5\t6\n", cap_bytes=10**6, max_rows=2)
    assert len(p.frame) == 2 and p.frame.attrs["capped"]


def test_refused():
    for name, data in [
        ("a.xls", b"x"),
        ("a.xlsm", b"x"),
        ("a.csv", b"PK\x03\x04zz"),
        ("a.xlsx", b"hello"),
        ("a.csv", b"a,b\n\x00\x01"),
    ]:
        with pytest.raises(f.UploadRefused):
            f.parse_file(name, data, cap_bytes=10**6, max_rows=10)


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    wb.active.append(["x", "y"])
    wb.active.append([1, "a"])
    wb.create_sheet("S2").append(["z"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_sheets():
    p = f.parse_file("a.xlsx", _xlsx(), cap_bytes=10**6, max_rows=10)
    assert p.sheet and list(p.frame.columns) == ["x", "y"]
    p2 = f.parse_file("a.xlsx", _xlsx(), cap_bytes=10**6, max_rows=10, sheet="S2")
    assert list(p2.frame.columns) == ["z"] or len(p2.frame) == 0
    with pytest.raises(f.UploadRefused):
        f.parse_file("a.xlsx", _xlsx(), cap_bytes=10**6, max_rows=10, sheet="nope")


def test_zip_bomb_and_entries():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("xl/workbook.xml", "x")
        z.writestr("big", b"0" * 200_000)
    with pytest.raises(f.UploadRefused, match="unpacked"):
        f.check_zip(buf.getvalue(), 1000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(1001):
            z.writestr(f"e{i}", "")
    with pytest.raises(f.UploadRefused, match="too many"):
        f.check_zip(buf.getvalue(), 10**6)


def test_macro_workbook_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("xl/workbook.xml", "x")
        z.writestr("xl/vbaProject.bin", "x")
    with pytest.raises(f.UploadRefused, match="macros"):
        f.check_zip(buf.getvalue(), 10**6)


def test_sanitize_name():
    assert f.sanitize_name("../../etc/pass\x00wd.csv") == "passwd.csv"
    assert f.sanitize_name(None) == "upload"


def test_wide_csv_header_refused_fast():
    import time

    data = (",".join(["a"] * 80_000) + "\n" + ",".join(["1"] * 80_000) + "\n").encode()
    t0 = time.perf_counter()
    with pytest.raises(f.UploadRefused, match="more than 500 columns"):
        f.parse_file("w.csv", data, cap_bytes=20_000_000, max_rows=1000)
    assert time.perf_counter() - t0 < 1.0


def test_csv_huge_header_line_and_field_refused():
    with pytest.raises(f.UploadRefused):
        f.parse_file("w.csv", b"a" * 1_100_000, cap_bytes=20_000_000, max_rows=10)
    data = b"a,b\n" + b"x" * 1_100_000 + b",1\n"
    with pytest.raises(f.UploadRefused, match="1 MB"):
        f.parse_file("w.csv", data, cap_bytes=20_000_000, max_rows=10)


def test_xlsx_streaming_limits():
    def book(rows):
        wb = openpyxl.Workbook()
        ws = wb.active
        for r in rows:
            ws.append(r)
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    wide = book([list(range(600)), list(range(600))])
    with pytest.raises(f.UploadRefused, match="more than 500 columns"):
        f.parse_file("w.xlsx", wide, cap_bytes=20_000_000, max_rows=100)
    tall = book([["a", "b"]] + [[i, "x"] for i in range(300)])
    p = f.parse_file("t.xlsx", tall, cap_bytes=20_000_000, max_rows=100)
    assert len(p.frame) == 100 and p.frame.attrs.get("capped") is True
