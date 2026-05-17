# DICOM Fixtures

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
