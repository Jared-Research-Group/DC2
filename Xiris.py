import sys
import os
import numpy as np
import io
from PIL import Image
import struct
import time
import threading
import queue
import zarr

import sensors
import DC2_helpers

logger = DC2_helpers.init_logger(__name__)

# add directories for compiled library + Xiris *.dll files
sys.path.insert(0, r".out\build\def\Release")
os.add_dll_directory(r"C:\Program Files\Xiris Automation Inc\Xiris WeldSDK 2\bin")

import xiris_bindings

class Xiris(sensors.BaseSensor):

    def __init__(self):

        super(Xiris, self).__init__()

        self.name = 'Xiris'
        self.acquisition_rate = 50 # defined by self.initialize
        self.shape = (640, 512) # is this a consistent byte count?
        self.dtype = np.int16
        self.columns = ('row', 'column')
        
        self.buffer_metas = queue.Queue()
        self.sample_meta = None

        self.camera_ip = None
        self.start_time = None
        self.first_frame_time = 0

    def detect(self, detection_timeout: int = 10):

        ip = xiris_bindings.detectCamera(detection_timeout) #type: ignore

        if ip == "-1":
            raise DC2_helpers.SensorNotConnectedError(sensor = self.name)

        else:
            self.camera_ip = ip

    def initialize(self, zarr_group=None, frame_rate: int = -1,  AoI = [0, 512, 0, 640]):

        if frame_rate != -1:
            self.acquisition_rate = frame_rate
            
        self.width = AoI[3] - AoI[2]
        self.height = AoI[1] - AoI[0]
        self.shape = (self.width, self.height)

        super(Xiris, self).initialize(zarr_group)
        
        if self.group is not None:
            self.meta = self.group.create_array(name = 'metadata', 
                                                shape = (0,), 
                                                chunks = self.time_chunk, 
                                                dimension_names = ('time',),
                                                dtype = 'U180')

            self.group.attrs['AoI'] = AoI
        
        [self.flag_initialized, msg] = xiris_bindings.initCamera(self.camera_ip, frame_rate, AoI) # type: ignore

        if not self.flag_initialized:
            raise Exception(f'{self.name}: {msg}')
        
    def writing_thread(self):
        
        time.sleep(.5)
        
        print('!')

        assert isinstance(self.collector_thread, threading.Thread)

        while self.collector_thread.is_alive():

            while not self.buffers.empty():

                self.data.append(self.buffers.get())
                self.time.append(self.buffer_times.get())
                self.meta.append(self.buffer_metas.get())
                
                print(f'{self.name}: len == {self.buffers.qsize()}')

    def collection_thread(self):

        [self.flag_is_collecting, msg] = xiris_bindings.startCamera() # type: ignore
        self.start_time = time.time_ns()

        if not self.flag_is_collecting:
            raise Exception(f'{self.name}: {msg}')
        
        with self.lock:
            flag_is_collecting = self.flag_is_collecting
        
        while flag_is_collecting: # type: ignore
            
            #print(f'Xiris: flag_is_collecting == {flag_is_collecting}')

            buffer      = np.zeros((self.buffer_len,) + self.shape, dtype = self.dtype)
            buffer_metas = np.zeros((self.buffer_len,), dtype = str)
            buffer_time = np.zeros((self.buffer_len,))

            for i in range(self.buffer_len):

                self.sample_sensor()

                buffer[i]      = self.sample
                buffer_metas[i] = self.sample_meta
                buffer_time[i] = self.sample_time

            if self.group is not None:
                self.buffers.put(buffer)
                self.buffer_metas.put(buffer_metas)
                self.buffer_times.put(buffer_time)
                
            with self.lock:
                flag_is_collecting = self.flag_is_collecting

        xiris_bindings.stopCamera() # type: ignore

        assert isinstance(self.buffer_len, int)

        while not xiris_bindings.cameraBufferIsEmpty(): # type: ignore

            buffer      = np.zeros((self.buffer_len,) + self.shape, dtype = self.dtype)
            buffer_metas = np.zeros((self.buffer_len,), dtype = str)
            buffer_time = np.zeros((self.buffer_len,))

            for i in range(self.buffer_len):

                self.sample_sensor()

                buffer[i]      = self.sample
                buffer_metas[i] = self.sample_meta
                buffer_time[i] = self.sample_time

            if self.group is not None:
                self.buffers.put(buffer)
                self.buffer_metas.put(buffer_metas)
                self.buffer_times.put(buffer_time)

    """
    @staticmethod
    def _split_raw_frame(data):
        "Efficiently read raw frame data using NumPy bulk read instead of pixel-by-pixel loop"
        
        if data == []:
            return [], [bytes([]), bytes([])], -1
        else:
            data = bytes(data)

        header = data[0:56]
        print(header[24:28])
    
        with io.BytesIO(header) as h:
            
            h.read(8)  # Skip header
            
            left   = int.from_bytes(h.read(4), 'little')
            top    = int.from_bytes(h.read(4), 'little')
            right  = int.from_bytes(h.read(4), 'little')
            bottom = int.from_bytes(h.read(4), 'little')
            width  = int.from_bytes(h.read(4), 'little')
            
            print(top)
            print(bottom)
            print(width)
            
            
            h.read(12)
            
            relative_time = int(struct.unpack('d', h.read(8))[0] * 10**9)

        height = bottom - top
        img_size = 2 * width * height
        
        img = Image.frombytes('I;16', [width, height], data[56:img_size + 56])
        img = np.asarray(img) * 2**2

        footer = data[img_size + 56:]
    
        return img, [header, footer], relative_time
    """

    def sample_sensor(self):
        img = np.empty(0)
        
        while np.array(img).size == 0:
            img, relative_time, meta = xiris_bindings.sampleCamera() # type: ignore
            
        img = np.array(img).reshape((self.width, self.height))
        
        if self.first_frame_time is None: 
            self.first_frame_time = relative_time
            self.group.attrs['first_frame_time'] = self.first_frame_time

        self.sample_time = self.start_time + (relative_time - self.first_frame_time)
        self.sample = img
        self.sample_meta = meta

    def __del__(self):

        if self.flag_initialized:
            xiris_bindings.deleteCamera() # type: ignore

if __name__ == '__main__':

    DC2_helpers.single_sensor_display(Xiris)