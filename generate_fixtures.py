import os
import zipfile
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.sequence import Sequence

fixtures_dir = "backend/tests/fixtures/dicom"
os.makedirs(fixtures_dir, exist_ok=True)

CT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2"
CT_MULTI_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2.1"
SEG_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.66.4"
RTSTRUCT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.481.3"
SR_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.88.11"


def base_file_meta(sop_class_uid, sop_instance_uid):
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = sop_class_uid
    file_meta.MediaStorageSOPInstanceUID = sop_instance_uid
    file_meta.ImplementationClassUID = "1.2.3.4"
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    return file_meta


def create_dicom(filename, sop_class_uid, sop_instance_uid, patient_name="Test^Patient",
                 missing_sop_uid=False, missing_sop_class=False):
    file_meta = base_file_meta(sop_class_uid, sop_instance_uid)
    path = os.path.join(fixtures_dir, filename)
    ds = FileDataset(path, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientName = patient_name
    ds.PatientID = "123456"
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.SeriesInstanceUID = "1.2.3.4.5.1"
    if not missing_sop_uid:
        ds.SOPInstanceUID = sop_instance_uid
    if not missing_sop_class:
        ds.SOPClassUID = sop_class_uid
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


def add_pixel_data(ds, pixel_bytes=b"\0"):
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows = 1
    ds.Columns = 1
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixel_bytes
    return ds


# ─── 1. Standard modality fixtures ─────────────────────────────────────────
ds_ct = create_dicom("valid_ct_single.dcm", CT_SOP_CLASS, "1.2.3.4.5.6.1")
ds_ct.save_as(os.path.join(fixtures_dir, "valid_ct_single.dcm"))

ds_ct_multi = create_dicom("valid_ct_multi_frame.dcm", CT_MULTI_SOP_CLASS, "1.2.3.4.5.6.2")
ds_ct_multi.save_as(os.path.join(fixtures_dir, "valid_ct_multi_frame.dcm"))

ds_rtstruct = create_dicom("valid_rtstruct.dcm", RTSTRUCT_SOP_CLASS, "1.2.3.4.5.6.3")
ds_rtstruct.save_as(os.path.join(fixtures_dir, "valid_rtstruct.dcm"))

ds_sr = create_dicom("valid_sr.dcm", SR_SOP_CLASS, "1.2.3.4.5.6.4")
ds_sr.save_as(os.path.join(fixtures_dir, "valid_sr.dcm"))

# ─── 2. SEG with real reference edges ───────────────────────────────────────
ds_seg = create_dicom("valid_seg.dcm", SEG_SOP_CLASS, "1.2.3.4.5.6.5")
ref_instance = pydicom.dataset.Dataset()
ref_instance.ReferencedSOPClassUID = CT_SOP_CLASS
ref_instance.ReferencedSOPInstanceUID = "1.2.3.4.5.6.1"  # points to valid_ct_single
ref_series = pydicom.dataset.Dataset()
ref_series.SeriesInstanceUID = "1.2.3.4.5.1"
ref_series.ReferencedInstanceSequence = Sequence([ref_instance])
ds_seg.ReferencedSeriesSequence = Sequence([ref_series])
ds_seg.save_as(os.path.join(fixtures_dir, "valid_seg.dcm"))

# ─── 3. Duplicate pairs ─────────────────────────────────────────────────────
# Identity duplicate: same SOPInstanceUID, different patient name (different hash)
ds_id_dup = create_dicom("identity_dup_b.dcm", CT_SOP_CLASS, "1.2.3.4.5.6.1",
                          patient_name="Duplicate^Patient")
ds_id_dup.save_as(os.path.join(fixtures_dir, "identity_dup_b.dcm"))

# Content duplicate: different SOPInstanceUID, same PixelData → same pixel_digest
SHARED_PIXEL = b"\xAB\xCD\xEF"
ds_dup_a = create_dicom("content_dup_a.dcm", CT_SOP_CLASS, "1.2.3.4.5.6.10")
add_pixel_data(ds_dup_a, SHARED_PIXEL)
ds_dup_a.save_as(os.path.join(fixtures_dir, "content_dup_a.dcm"))

ds_dup_b = create_dicom("content_dup_b.dcm", CT_SOP_CLASS, "1.2.3.4.5.6.11")
add_pixel_data(ds_dup_b, SHARED_PIXEL)
ds_dup_b.save_as(os.path.join(fixtures_dir, "content_dup_b.dcm"))

# ─── 4. Private tags (two creators) ─────────────────────────────────────────
ds_private = create_dicom("valid_private_tags.dcm", CT_SOP_CLASS, "1.2.3.4.5.6.20")
ds_private.add_new((0x0009, 0x0010), 'LO', 'CREATOR_A')
ds_private.add_new((0x0009, 0x1001), 'SH', 'Vendor A Data')
ds_private.add_new((0x000B, 0x0010), 'LO', 'CREATOR_B')
ds_private.add_new((0x000B, 0x1001), 'SH', 'Vendor B Data')
ds_private.save_as(os.path.join(fixtures_dir, "valid_private_tags.dcm"))

# ─── 5. Invalid/malformed fixtures ──────────────────────────────────────────
# missing_required_tag: no SOPInstanceUID (matches 012 backlog spec)
ds_missing = create_dicom("missing_required_tag.dcm", CT_SOP_CLASS, "1.2.3.4.5.6.30",
                           missing_sop_uid=True)
ds_missing.save_as(os.path.join(fixtures_dir, "missing_required_tag.dcm"))

# truncated: valid magic bytes, abruptly cut off
with open(os.path.join(fixtures_dir, "truncated.dcm"), "wb") as f:
    f.write(b"\0" * 128 + b"DICM" + b"\x08\x00\x05\x00\x43\x53\x0a\x00ISO_IR 100")

with open(os.path.join(fixtures_dir, "not_dicom.txt"), "w") as f:
    f.write("This is a plain text file, not DICOM.")

# ─── 6. ZIP fixtures ─────────────────────────────────────────────────────────
# 42 stubs
with zipfile.ZipFile(os.path.join(fixtures_dir, "valid_zip_42_files.zip"), "w") as zf:
    for i in range(42):
        zf.writestr(f"file_{i:02d}.dcm", b"\0" * 128 + b"DICM")

# Zip bomb: small file claiming huge expansion (use 10x 1MB of zeros, compressed)
with zipfile.ZipFile(os.path.join(fixtures_dir, "zip_bomb.zip"), "w", compression=zipfile.ZIP_DEFLATED) as zf:
    chunk = b"0" * (1024 * 1024 * 10)   # 10 MB each, 10 entries = 100 MB claimed
    for i in range(10):
        zf.writestr(f"bomb_{i}.bin", chunk)

# Path traversal
with zipfile.ZipFile(os.path.join(fixtures_dir, "zip_path_traversal.zip"), "w") as zf:
    zf.writestr("../etc/passwd", b"root:x:0:0::/root:/bin/sh")

# Nested 3-deep
inner = os.path.join(fixtures_dir, "_tmp_inner.zip")
mid   = os.path.join(fixtures_dir, "_tmp_mid.zip")
with zipfile.ZipFile(inner, "w") as zf:
    zf.writestr("test.dcm", b"DICM")
with zipfile.ZipFile(mid, "w") as zf:
    zf.write(inner, "inner.zip")
with zipfile.ZipFile(os.path.join(fixtures_dir, "zip_nested_3_deep.zip"), "w") as zf:
    zf.write(mid, "mid.zip")
os.remove(inner)
os.remove(mid)

# Mixed content: valid DICOM + non-DICOM + malformed
with zipfile.ZipFile(os.path.join(fixtures_dir, "mixed_content.zip"), "w") as zf:
    zf.write(os.path.join(fixtures_dir, "valid_ct_single.dcm"), "valid.dcm")
    zf.write(os.path.join(fixtures_dir, "not_dicom.txt"), "bad.txt")
    zf.write(os.path.join(fixtures_dir, "truncated.dcm"), "malformed.dcm")

# ─── 7. README ───────────────────────────────────────────────────────────────
with open(os.path.join(fixtures_dir, "README.md"), "w") as f:
    f.write("""\
# DICOM Fixtures — Golden Set

All fixtures in this directory are generated by `/generate_fixtures.py`.
Run `python3 generate_fixtures.py` from the project root to regenerate.

## Standard Modality Fixtures
| File | SOP Class | Purpose |
|---|---|---|
| `valid_ct_single.dcm` | CT Image | Base reference CT |
| `valid_ct_multi_frame.dcm` | Enhanced CT | Multi-frame path |
| `valid_rtstruct.dcm` | RT Structure Set | Radiotherapy modality |
| `valid_sr.dcm` | Basic SR | Structured report modality |
| `valid_seg.dcm` | Segmentation | Has `ReferencedSOPInstanceUID` pointing to `valid_ct_single.dcm` |

## Duplicate Pair Fixtures
| File | Purpose |
|---|---|
| `valid_ct_single.dcm` + `identity_dup_b.dcm` | Identity duplicate pair: same `SOPInstanceUID`, different bytes/hash |
| `content_dup_a.dcm` + `content_dup_b.dcm` | Content duplicate pair: different `SOPInstanceUID`, same `PixelData` → same `pixel_digest` |

## Private Tag Fixture
| File | Purpose |
|---|---|
| `valid_private_tags.dcm` | Has private tags from `CREATOR_A` (0009) and `CREATOR_B` (000B) |

## Invalid/Malformed Fixtures
| File | Expected Outcome |
|---|---|
| `missing_required_tag.dcm` | No `SOPInstanceUID` → parser raises `MissingRequiredDicomTag` |
| `truncated.dcm` | Valid preamble but abruptly cut off → `DicomParseFailed` |
| `not_dicom.txt` | No DICM magic bytes → rejected at scan stage |

## ZIP Fixtures
| File | Purpose |
|---|---|
| `valid_zip_42_files.zip` | 42 minimal valid-looking DICOM stubs |
| `zip_bomb.zip` | ~100 MB of zeros compressed; should raise `ZipBombDetected` before full extraction |
| `zip_path_traversal.zip` | Contains `../etc/passwd`; should raise `UnsafeArchivePath` |
| `zip_nested_3_deep.zip` | Zip inside zip inside zip; should fail nesting-depth limit |
| `mixed_content.zip` | Valid DICOM + plain text + malformed DICOM; tests sibling survival / partial rejection |
""")

print("✓ Fixtures generated successfully.")
