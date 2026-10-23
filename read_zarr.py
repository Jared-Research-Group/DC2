import zarr
from pathlib import Path

time_path = Path(r"D:\mason\testing DC2\data_collection20261023_173810.zarr\LEMBox\time")


time = zarr.open_array(time_path)
time = time[:] * 1e-9
time -= time[0]
print(time)
print(len(time))

print(len(time) / time[-1])


data_path = Path(r"D:\mason\testing DC2\data_collection20261023_173810.zarr\LEMBox\data")

data = zarr.open_array(data_path)[:]
print(len(data))

print(len(data) / time[-1])