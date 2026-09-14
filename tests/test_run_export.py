"""mzML / mzXML export of a whole multi-scan run (mspy.writeMZML, mspy.writeMZXML).

Both writers take one scan or a list of scans. A run must read back through the
mMass parsers scan for scan -- data, peaks and the metadata that decides which
scans can be pooled -- and the indexed files must stay internally consistent.
"""

import hashlib
import re

import numpy
import pytest

import mspy


def _run():
    """Two interleaved MS1 scan types and a centroided MS2, as a Thermo DDA run."""

    scans = []
    x = numpy.linspace(400.0, 410.0, 200)
    for index, (filterString, height) in enumerate(
        [("FTMS + p ESI Full ms", 100.0), ("ITMS + p ESI Full ms", 40.0),
         ("FTMS + p ESI Full ms", 120.0), ("ITMS + p ESI Full ms", 50.0)]
    ):
        y = height * numpy.exp(-0.5 * ((x - 405.0) / 0.01) ** 2) + 1.0
        scan = mspy.scan(profile=numpy.column_stack([x, y]))
        scan.scanNumber = index + 1
        scan.msLevel = 1
        scan.polarity = 1
        scan.retentionTime = 60.0 + 3.0 * index
        scan.attributes["filterString"] = filterString
        if index == 0:
            peak = mspy.peak(mz=405.0, ai=101.0, base=1.0, charge=1, fwhm=0.02)
            scan.setpeaklist(mspy.peaklist([peak]))
        scans.append(scan)

    ms2 = mspy.scan(peaklist=mspy.peaklist([mspy.peak(mz=150.5, ai=10.0), mspy.peak(mz=300.25, ai=40.0)]))
    ms2.scanNumber = 5
    ms2.parentScanNumber = 1
    ms2.msLevel = 2
    ms2.polarity = 1
    ms2.retentionTime = 73.0
    ms2.precursorMZ = 405.0
    ms2.precursorCharge = 2
    scans.append(ms2)

    return scans


@pytest.mark.parametrize(
    "writer, parser, extension",
    [(mspy.writeMZML, mspy.parseMZML, "mzML"), (mspy.writeMZXML, mspy.parseMZXML, "mzXML")],
)
def test_whole_run_reads_back_scan_for_scan(tmp_path, writer, parser, extension):
    scans = _run()
    path = str(tmp_path / ("run." + extension))
    writer(scans, {"title": "run"}).write(path)

    reader = parser(path)
    scanlist = reader.scanlist()
    assert sorted(scanlist) == [1, 2, 3, 4, 5]

    for original in scans:
        meta = scanlist[original.scanNumber]
        assert meta["msLevel"] == original.msLevel
        assert meta["retentionTime"] == pytest.approx(original.retentionTime, abs=1e-3)
        assert meta.get("filterString") == original.attributes.get("filterString")

        scan = reader.scan(original.scanNumber)
        assert scan is not False
        assert numpy.allclose(scan.profile, original.profile) if original.hasprofile() else not scan.hasprofile()
        assert [round(p.mz, 4) for p in scan.peaklist] == [round(p.mz, 4) for p in original.peaklist]

    assert scanlist[5]["precursorMZ"] == pytest.approx(405.0)

    # the acquisition type survives, so the reopened run still pools correctly
    groups = mspy.acquisitiongroups(scanlist)
    assert [1, 3] in groups and [2, 4] in groups


def test_mzml_run_index_and_checksum_are_consistent(tmp_path):
    path = tmp_path / "run.mzML"
    mspy.writeMZML(_run(), {"title": "run"}).write(str(path))
    data = path.read_bytes()

    checked = data[: data.index(b"<fileChecksum>") + len(b"<fileChecksum>")]
    assert hashlib.sha1(checked).hexdigest().encode() == re.search(
        rb"<fileChecksum>([0-9a-f]+)<", data
    ).group(1)

    offsets = [int(m.group(1)) for m in re.finditer(rb'<offset idRef="[^"]*">(\d+)<', data)]
    assert len(offsets) == 6  # five spectra and the TIC chromatogram
    assert all(data[o:o + 9] in (b"<spectrum", b"<chromato") for o in offsets)
    listOffset = int(re.search(rb"<indexListOffset>(\d+)<", data).group(1))
    assert data[listOffset:listOffset + 10] == b"<indexList"

    # TIC over the four MS1 scans, in retention-time order
    assert b'<chromatogram index="0" id="TIC" defaultArrayLength="4">' in data
    assert b'<spectrumList count="5"' in data
    # precursor carries the element the schema requires
    assert b"<activation/>" in data


def test_single_scan_export_keeps_its_shape(tmp_path):
    """One scan is still one spectrum, with no chromatogram and one index."""

    scan = _run()[0]
    text = mspy.writeMZML(scan, {"title": "one"}).tostring()

    assert '<spectrumList count="1"' in text
    assert 'id="scan=1"' in text
    assert "<chromatogramList" not in text
    assert '<indexList count="1">' in text


def test_scans_without_numbers_get_unique_ids(tmp_path):
    scans = _run()[:3]
    for scan in scans:
        scan.scanNumber = None
    scans[2].scanNumber = 1  # collides with the id the first scan falls back to

    text = mspy.writeMZML(scans).tostring()
    ids = re.findall(r'<spectrum index="\d+" id="([^"]*)"', text)

    assert len(set(ids)) == 3
