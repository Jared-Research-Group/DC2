import sys
import os
import numpy as np
import io
from PIL import Image
import struct
import time
import threading
import queue

import sensors
import DC2_helpers

logger = DC2_helpers.init_logger(__name__)

# add directories for compiled library + Xiris *.dll files
sys.path.insert(0, r".out\build\def\Release")
os.add_dll_directory(r"C:\Program Files\Xiris Automation Inc\Xiris WeldSDK 2\bin")

import xiris

class Xiris(sensors.BaseSensor):

    def __init__(self):

        super(Xiris, self).__init__()

        self.name = 'Xiris'
        self.acquisition_rate = 50 # defined by self.initialize
        self.shape = (640, 512) # is this a consistent byte count?
        self.dtype = np.int16
        self.columns = ('row', 'column')
        
        self.buffers_meta = queue.Queue()
        self.sample_meta = None

        self.camera_ip = None
        self.start_time = None
        self.first_frame_time = None

    def detect(self, detection_timeout: int = 10):

        ip = xiris.detectCamera(detection_timeout) #type: ignore

        if ip == "-1":
            raise DC2_helpers.SensorNotConnectedError(sensor = self.name)

        else:
            self.camera_ip = ip

    def initialize(self, zarr_group=None, frame_rate: int = -1,  AoI = [0, 512, 0, 640]):

        if frame_rate != -1:
            self.acquisition_rate = frame_rate

        super(Xiris, self).initialize(zarr_group)
        
        self.meta = self.group.create_array(name = 'metadata', 
                                            shape = (0, 2), 
                                            chunks = self.time_chunk + (1,), 
                                            dimension_names = ('time', 'head/foot'),
                                            dtype = bytearray)

        self.group.attrs['AoI'] = AoI
        
        [self.flag_initialized, msg] = xiris.initCamera(self.camera_ip, frame_rate, AoI) # type: ignore

        if not self.flag_initialized:
            raise Exception(f'{self.name}: {msg}')
        
    def writing_thread(self):
        
        time.sleep(.5)

        assert isinstance(self.collector_thread, threading.Thread)

        while self.collector_thread.is_alive():

            while not self.buffers.empty():

                self.data.append(self.buffers.get())
                self.time.append(self.buffer_times.get())
                self.meta.append(self.buffer_meta.get())

    def collection_thread(self):

        [self.flag_is_collecting, msg] = xiris.startCamera() # type: ignore
        self.start_time = time.time_ns()

        if not self.flag_is_collecting:
            raise Exception(f'{self.name}: {msg}')

        super(Xiris, self).collection_thread()

        xiris.stopCamera() # type: ignore

        assert isinstance(self.buffer_len, int)

        while not xiris.cameraBufferIsEmpty(): # type: ignore

            buffer      = np.zeros((self.buffer_len,) + self.shape, dtype = self.dtype)
            buffer_meta = np.zeros((self.buffer_len, 2), dtype = bytearray)
            buffer_time = np.zeros((self.buffer_len,))

            for i in range(self.buffer_len):

                self.sample_sensor()

                buffer[i]      = self.sample
                buffer_meta[i] = self.sample_meta
                buffer_time[i] = self.sample_time

            if self.group is not None:
                self.buffers.put(buffer)
                self.buffers_meta.put(buffer_meta)
                self.buffer_times.put(buffer_time)

    def _split_raw_frame(data):
        """Efficiently read raw frame data using NumPy bulk read instead of pixel-by-pixel loop"""

        header = data[0:56]
    
        with io.BytesIO(header) as h:
            
            h.read(8)  # Skip header
            
            left   = int.from_bytes(h.read(4), 'little')
            top    = int.from_bytes(h.read(4), 'little')
            right  = int.from_bytes(h.read(4), 'little')
            bottom = int.from_bytes(h.read(4), 'little')
            width  = int.from_bytes(h.read(4), 'little')
            
            h.read(12)
            
            relative_time = struct.unpack('d', h.read(8))[0]

        height = bottom - top
        img_size = 2 * width * height
        
        img = Image.frombytes('I;16', [width, height], data[56:img_size + 56])
        img = np.asarray(img) * 2**2

        footer = data[img_size + 56:]
    
        return img, [header, footer], relative_time

    def sample_sensor(self):

        sample = xiris.sampleCamera() # type: ignore
        
        data, meta, relative_time = self._split_raw_frame(bytes(sample))
        
        if self.first_frame_time is None: 
            self.first_frame_time = relative_time
            self

        self.sample_time = self.start_time + (relative_time - self.first_frame_time)
        self.sample = data
        self.sample_meta = meta

    def __del__(self):

        if self.flag_initialized:
            xiris.deleteCamera() # type: ignore

if __name__ == '__main__':

    DC2_helpers.single_sensor_display(Xiris)