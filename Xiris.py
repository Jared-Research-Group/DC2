import sys
import os
import numpy as np
import io
from PIL import Image

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
        self.shape = (1, 3) # is this a consistent byte count?
        self.dtype = np.int16
        self.columns = ('Frame', 'data')

        self.camera_ip = None

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

        self.group.attrs['AoI'] = AoI
        
        [self.flag_initialized, msg] = xiris.initCamera(self.camera_ip, frame_rate, AoI) # type: ignore

        if not self.flag_initialized:
            raise Exception(f'{self.name}: {msg}')

    def collection_thread(self):

        [self.flag_is_collecting, msg] = xiris.startCamera() # type: ignore

        if not self.flag_is_collecting:
            raise Exception(f'{self.name}: {msg}')

        super(Xiris, self).collection_thread()

        xiris.stopCamera() # type: ignore

        assert isinstance(self.buffer_len, int)

        while not xiris.cameraBufferIsEmpty(): # type: ignore

            buffer      = np.zeros((self.buffer_len,) + self.shape, dtype = self.dtype)
            buffer_time = np.zeros((self.buffer_len,))

            for i in range(self.buffer_len):

                self.sample_sensor()

                buffer[i]      = self.sample
                buffer_time[i] = self.sample_time

            if self.group is not None:
                self.buffers.put(buffer)
                self.buffer_times.put(buffer_time)

    def convertFrame(data):
        """Efficiently read raw frame data using NumPy bulk read instead of pixel-by-pixel loop"""
    
        with io.BytesIO(data) as frame:
            frame.read(8)  # Skip header
            left   = int.from_bytes(frame.read(4), 'little')
            top    = int.from_bytes(frame.read(4), 'little')
            right  = int.from_bytes(frame.read(4), 'little')
            bottom = int.from_bytes(frame.read(4), 'little')
            width  = int.from_bytes(frame.read(4), 'little')
            height = bottom - top
    
            frame.read(28)  # Skip remaining header
        
            img = Image.frombytes('I;16', [width, height], frame.read(2 * width * height))
            intensity = np.asarray(img) * 2**2
    
        return intensity

    def sample_sensor(self):

        sample = xiris.sampleCamera() # type: ignore

        self.sample_time = sample[0]
        self.sample = bytes(sample[1])

    def __del__(self):

        if self.flag_initialized:
            xiris.deleteCamera() # type: ignore

if __name__ == '__main__':

    DC2_helpers.single_sensor_display(Xiris)