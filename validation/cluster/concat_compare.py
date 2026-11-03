"""Run concatenate_files with the bruker_concat_tif module found in <module_dir>, and time it.

    python concat_compare.py <module_dir> <out_dir> <raw_folder> [<raw_folder> ...]
"""

import sys, time, importlib
sys.path.insert(0, sys.argv[1])
ct = importlib.import_module("bruker_concat_tif")
print("module:", ct.__file__)
t = time.time()
ct.concatenate_files(sys.argv[3:], sys.argv[2], regex="*_Ch2_*.ome.tif", scale_range=False)
print(f"TOTAL {time.time() - t:.1f} s")
