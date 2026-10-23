import zarr
from pathlib import Path

path = Path(r"D:\mason\testing DC2\data_collection20261022_183857.zarr\Xiris\time")

time = zarr.open_array(path)
time = time[:] * 1e-9
time -= time[0]
print(time)
print(len(time))

print(len(time) / time[-1])