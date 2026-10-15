import zarr
import pandas as pd
import numpy as np
from datetime import datetime

import DC2_helpers

#dir = DC2_helpers.select_folder()
dir = r'D:\mason\testing DC2\data_collection20260821_170726.zarr'
data = zarr.open_group(dir, mode='r')

#print(np.array(data['Microphone']['data']))

time = np.array(data['Microphone']['time'])

#print(time)

print((time[-1] - time[0]) * 1e-9)

print(len(time))

