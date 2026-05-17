import os
import zipfile
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset

fixtures_dir = "backend/tests/fixtures/dicom"
os.makedirs(fixtures_dir, exist_ok=True)

def create_dummy_dicom(filename, sop_class_uid, missing_tag=False):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.5.6.7"
    file_meta.ImplementationClassUID = "1.2.3.4"
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    
    ds = FileDataset(os.path.join(fixtures_dir, filename), {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientName = "Test^Patient"
    if not missing_tag:
        ds.PatientID = "123456"
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.SeriesInstanceUID = "1.2.3.4.5.1"
    ds.SOPInstanceUID = "1.2.3.4.5.6.7"
    ds.SOPClassUID = sop_class_uid
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    
    ds.save_as(os.path.join(fixtures_dir, filename))

create_dummy_dicom("valid_ct_single.dcm", "1.2.840.10008.5.1.4.1.1.2")
create_dummy_dicom("valid_ct_multi_frame.dcm", "1.2.840.10008.5.1.4.1.1.2.1")
create_dummy_dicom("valid_seg.dcm", "1.2.840.10008.5.1.4.1.1.66.4")
create_dummy_dicom("valid_rtstruct.dcm", "1.2.840.10008.5.1.4.1.1.481.3")
create_dummy_dicom("valid_sr.dcm", "1.2.840.10008.5.1.4.1.1.88.11")
create_dummy_dicom("missing_required_tag.dcm", "1.2.840.10008.5.1.4.1.1.2", missing_tag=True)

with open(os.path.join(fixtures_dir, "truncated.dcm"), "wb") as f:
    f.write(b"\0" * 128 + b"DICM" + b"\x08\x00\x05\x00\x43\x53\x0a\x00ISO_IR 100")

with open(os.path.join(fixtures_dir, "not_dicom.txt"), "w") as out:
    out.write("This is a text file.")

with zipfile.ZipFile(os.path.join(fixtures_dir, "valid_zip_42_files.zip"), "w") as zf:
    for i in range(42):
        zf.writestr(f"file_{i}.dcm", b"\0" * 128 + b"DICM")

with zipfile.ZipFile(os.path.join(fixtures_dir, "zip_bomb.zip"), "w", compression=zipfile.ZIP_DEFLATED) as zf:
    chunk = b"0" * 1024 * 1024 * 10
    for i in range(10):
        zf.writestr(f"bomb_{i}.txt", chunk)

with zipfile.ZipFile(os.path.join(fixtures_dir, "zip_path_traversal.zip"), "w") as zf:
    zf.writestr("../etc/passwd", b"root:x:0:0:root:/root:/bin/bash")

with zipfile.ZipFile("inner.zip", "w") as zf:
    zf.writestr("test.dcm", b"DICM")
with zipfile.ZipFile("mid.zip", "w") as zf:
    zf.write("inner.zip")
with zipfile.ZipFile(os.path.join(fixtures_dir, "zip_nested_3_deep.zip"), "w") as zf:
    zf.write("mid.zip")
os.remove("inner.zip")
os.remove("mid.zip")

with open(os.path.join(fixtures_dir, "README.md"), "w") as f:
    f.write('''# DICOM Fixtures

- `valid_ct_single.dcm`: A valid simulated CT image (using pydicom).
- `valid_ct_multi_frame.dcm`: A valid simulated multi-frame CT.
- `valid_seg.dcm`: A valid simulated Segmentation object.
- `valid_rtstruct.dcm`: A valid simulated RT Structure Set.
- `valid_sr.dcm`: A valid simulated Structured Report.
- `missing_required_tag.dcm`: Missing PatientID tag, useful for parser failure tests.
- `truncated.dcm`: Valid preamble and magic bytes but abruptly truncated.
- `not_dicom.txt`: Pure text file, should fail magic byte check.
- `valid_zip_42_files.zip`: 42 small dicom-like files.
- `zip_bomb.zip`: 100MB of zeroes compressed into a tiny size, fails size limit.
- `zip_path_traversal.zip`: Contains `../etc/passwd`, fails safety checks.
- `zip_nested_3_deep.zip`: Fails nested depth limit checks.
''')
