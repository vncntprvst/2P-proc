#%%
import numpy as np
from pathlib import Path

data_path = Path('/home/wanglab/data/2P/C57_O1M2/10052023/run1run2run3run4run5')  # Change this to your actual path

#%%
F = np.load(data_path / 'F.npy', allow_pickle=True)
Fneu = np.load(data_path / 'Fneu.npy', allow_pickle=True)
spks = np.load(data_path / 'spks.npy', allow_pickle=True)
stat = np.load(data_path / 'stat.npy', allow_pickle=True)
ops =  np.load(data_path / 'ops.npy', allow_pickle=True)
ops = ops.item()
iscell = np.load(data_path / 'iscell.npy', allow_pickle=True)

print('Data loaded successfully.')

#%%
# Print info from stat
print(f"stat contains {len(stat)} cells.")
print(f"Keys in each cell dictionary: {list(stat[0].keys())}")

for i, cell in enumerate(stat):
    print(f"Cell {i}:")
    print(f"  xpix: {cell['xpix'][:5]}...")  # Print first 5 xpix values
    print(f"  ypix: {cell['ypix'][:5]}...")  # Print first 5 ypix values
    print(f"  lam: {cell['lam']}")
    print(f"  med: {cell['med']}")
    print(f"  footprint shape: {cell['footprint'].shape}")
    print(f"  mrs: {cell['mrs']}")
    print(f"  mrs0: {cell['mrs0']}")
    print(f"  compact: {cell['compact']}")
    print(f"  solidity: {cell['solidity']}")
    print(f"  npix: {cell['npix']}")
    print(f"  npix_soma: {cell['npix_soma']}")
    print(f"  soma_crop: {cell['soma_crop']}")
    print(f"  overlap: {cell['overlap']}")
    print(f"  radius: {cell['radius']}")
    print(f"  aspect_ratio: {cell['aspect_ratio']}")
    print(f"  npix_norm_no_crop: {cell['npix_norm_no_crop']}")
    print(f"  npix_norm: {cell['npix_norm']}")
    print(f"  skew: {cell['skew']}")
    print(f"  std: {cell['std']}")
    print(f"  neuropil_mask shape: {cell['neuropil_mask'].shape}")
    if i >= 2:  # Limit output to first 3 cells for brevity
        break
    
#%%
print(f"ops contains keys: {list(ops.keys())}")
print(f"F shape: {F.shape}")
print(f"Fneu shape: {Fneu.shape}")
print(f"spks shape: {spks.shape}")
print(f"iscell shape: {iscell.shape}, values: {iscell[:10]}")  # Print first 10 iscell values

