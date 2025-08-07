#%%
import numpy as np
from pathlib import Path
import sys
from pathlib import Path
import numpy as np

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Mesmerize.utils.pipeline_utils import (
    log_and_print, 
    load_mmap_movie, 
    clip_range,
)


#%%
export_path = Path('/home/wanglab/data/2P/Analysis_2P/C57_O1M2/10022023/run1/test_mcorr_module')
memmap_path = export_path / '41bbed4f-ae96-409e-9fbe-a8400016e43c/41bbed4f-ae96-409e-9fbe-a8400016e43c-cat_tiff_bt_els__d1_765_d2_765_d3_1_order_F_frames_1600.mmap'
bin_path = export_path / 'test_mcorr_movie.bin'
log_and_print(f"Saving .bin movie to {bin_path}")

#%%
# Load the memmap movie as (frames, Ly, Lx)
memmap_array = load_mmap_movie(memmap_path)

#%% 
# Add this debugging cell right after loading
print(f"Memmap path exists: {memmap_path.exists()}")
print(f"Memmap path: {memmap_path}")

# Try loading with error handling
try:
    memmap_array = load_mmap_movie(memmap_path)
    print(f"Successfully loaded memmap_array")
    print(f"Type: {type(memmap_array)}")
    print(f"Shape: {memmap_array.shape}")
    print(f"Dtype: {memmap_array.dtype}")
    print(f"First few values: {memmap_array.flat[:10]}")
except Exception as e:
    print(f"Error loading memmap: {e}")
    import traceback
    traceback.print_exc()

#%%
# Clip and convert to uint16 for Suite2p (or use .astype(np.float32) if desired)
memmap_array = clip_range(memmap_array, 'uint16').astype(np.uint16)
# Note that Suite2p expects float32 data for .bin files by default, 
# but the data type can be specified in the ops dictionary: ops['data_dtype'] = 'uint16'.
# We use uint16 here to save space and because the data does not use bit depth beyond 16 bits.

# Optional: Check shape
if memmap_array.ndim != 3:
    raise ValueError("Expected memmap array shape (frames, Ly, Lx), got: {}".format(memmap_array.shape))

print(f"Converted memmap_array to uint16")
print(f"Type: {type(memmap_array)}")
print(f"Shape: {memmap_array.shape}")
print(f"Dtype: {memmap_array.dtype}")
print(f"First few values: {memmap_array.flat[:10]}")

#%%
import matplotlib.pyplot as plt

# Create figure
fig, ax = plt.subplots(1, 2, figsize=(10, 5))

# Plot first frame before C-ordering
ax[0].imshow(memmap_array[0], cmap='gray')
ax[0].set_title('First Frame before c-ordering')
ax[0].axis('off')

# Ensure C-order (row-major)
memmap_array_c_order = np.ascontiguousarray(memmap_array)

# Plot first frame after C-ordering  
ax[1].imshow(memmap_array_c_order[0], cmap='gray')
ax[1].set_title('First Frame after c-ordering')
ax[1].axis('off')

# Finalize and save
plt.tight_layout()
plt.savefig(Path(bin_path).with_suffix('.png'))
plt.show()  # Display in notebook
plt.close(fig)

# Update memmap_array with C-ordered version
memmap_array = memmap_array_c_order

#%% 
print(f"Converted memmap_array C-order")
print(f"Type: {type(memmap_array)}")
print(f"Shape: {memmap_array.shape}")
print(f"Dtype: {memmap_array.dtype}")
print(f"First few values: {memmap_array.flat[:10]}")

#%%
# Save as binary file
with open(bin_path, 'wb') as f:
    memmap_array.tofile(f)

log_and_print(f"Saved .bin movie to {bin_path}")

#%%
# Verify the saved binary file: load then plot the first frame
with open(bin_path, 'rb') as f:
    loaded_array = np.fromfile(f, dtype=np.uint16)
    loaded_array = loaded_array.reshape(memmap_array.shape)
print(f"Loaded array shape: {loaded_array.shape}")
plt.imshow(loaded_array[0], cmap='gray')
plt.title('First Frame from Saved .bin')
plt.axis('off')
plt.show()
# %%
