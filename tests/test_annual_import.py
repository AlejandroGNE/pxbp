import hashlib
import json
import zipfile

import pytest

from pxbp.annual_import import import_annual_zip
from pxbp.sources import Selection, Source, stream_query


def archive(tmp_path, body):
    path = tmp_path / "solution.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("Model Example Generator Units Built.csv", body)
    return path


def test_native_annual_import_queries_parquet(tmp_path):
    path = archive(tmp_path, 'Name,Year,Month,Day,Period,Value\n"Plant, A",2031,1,1,1,0.5\n"Plant, A",2032,1,1,1,1.25\n')
    output = import_annual_zip(path, tmp_path / "parquet")
    selection = Selection({"collection": "SystemGenerators", "properties": "Units Built", "phase": "NativeAnnual", "period": "Year"})
    batches = list(stream_query([Source("A", path=str(output))], selection))
    assert batches[0].frame.sort_values("start_date").value.tolist() == [.5, 1.25]
    assert batches[0].frame.object_name.tolist() == ["Plant, A", "Plant, A"]
    provenance = json.loads((output / "import-provenance.json").read_text())
    assert provenance["archive_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert not list(output.rglob("*.csv"))
    with pytest.raises(ValueError, match="new import"):
        import_annual_zip(path, output)


@pytest.mark.parametrize("body,reason", [
    ("Name,Year,Value\nPlant,2031,1\nPlant,2031,2\n", "Duplicate"),
    ("Name,Year,Month,Value\nPlant,2031,2,1\n", "subannual"),
    ("Name,Year,Value\nPlant,2031,nan\n", "nonfinite"),
    ("Name,Year,Value\nPlant,2031,-1\n", "negative"),
])
def test_invalid_native_summary_does_not_publish_partial_import(tmp_path, body, reason):
    output = tmp_path / "parquet"
    with pytest.raises(ValueError, match=reason):
        import_annual_zip(archive(tmp_path, body), output)
    assert not output.exists()
