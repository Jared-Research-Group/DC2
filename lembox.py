import sensors
import DC2_helpers

logger = DC2_helpers.init_logger(__name__)

import numpy as np
import sys
sys.path.insert(0, ".out/build/def/Release")

import lembox

class LEMBox(sensors.BufferedSensor):

    def __init__(self):

        super(LEMBox, self).__init__()

        self.name = 'LEMBox'
        self.acquisition_rate = 20e3
        self.shape = (2,)
        self.dtype = np.float64
        self.columns = ('Voltage(V)', 'Current(A)')

        self.flag_connected = False

    def detect(self):

        [flag_detected, msg] = lembox.detectBoard() # type: ignore

        if not flag_detected:
            logger.error(msg)
            raise DC2_helpers.SensorNotConnectedError(sensor = self.name)

        else:

            self.flag_connected = flag_detected

    def initialize(self, zarr_group):

        super(LEMBox, self).initialize(zarr_group) #TODO: make flag_initialized a decorator for initialize

        [self.flag_initialized, msg] = lembox.initBoard(freq = self.acquisition_rate, buffer_len = self.buffer_len) # type: ignore

        if not self.flag_initialized:
            raise Exception(f'{self.name}: {msg}')

    def collection_thread(self):

        self.last_time = lembox.startCollection() # type: ignore

        self.timestep = 1 / self.acquisition_rate * 1e9

        if self.last_time == -1:
            raise Exception("Error starting LEMBox collection")

        super(LEMBox, self).collection_thread()

    def sample_sensor(self):

        self.buffer = np.array(lembox.sampleBuffer()) # type: ignore
        
        if self.buffer.size > 0:
            self.buffer_time = np.astype(((np.arange(len(self.buffer[0])) / self.acquisition_rate) * 1e9) + self.last_time + self.timestamp, np.uint64)
            self.last_time = self.buffer_time[-1]
            
        else:
            self.buffer_time = np.array([])

        if self.group is not None:
            self.buffers.put(self.buffer)
            self.buffer_times.put(self.buffer_time)
            
    def stop_collection(self):
    
        lembox.stopCollection() # type: ignore
        
        super(LEMBox, self).stop_collection()

    def __del__(self):

        if self.flag_connected:
            lembox.deleteBoard() # type: ignore

if __name__ == '__main__': 

    DC2_helpers.single_sensor_display(LEMBox)
