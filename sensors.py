# generic imports
import math
import threading
import zarr
import numpy as np
import queue
import time

# project imports
import DC2_helpers

logger = DC2_helpers.init_logger(__name__)

class BaseSensor:
    """
    Virtual class representing an arbitrary sensor. The general workflow for a sensor is:
        initialize sensor variables -> detect sensor presence -> initialize sensor -> start sensor collection -> stop sensor collection
    """
    
    def __init__(self):
        
        self.name             = '' # name of sensor
        self.acquisition_rate = None # expected acquisition rate. Used to determine zarr chunk size
        self.shape            = tuple() # shape of a single sample. e.g. 64x64 image = (,64,64); 1D timeseries = (1,) 
        self.dtype            = np.float64
        self.columns          = tuple()
        
        self.flag_initialized   = False
        self.flag_is_collecting = False
        
        self.lock = threading.Lock()
        self.collector_thread = None
        self.writer_thread    = None

        self.group   = None
        self.time_chunk   = None
        self.data_chunk   = None
        self.buffer_len   = None
        self.buffer_times = queue.Queue()
        self.buffers      = queue.Queue() # list of npy arrays of len buffer_len
        self.sample_time  = None
        self.sample       = None  # holds a single sample recorded by the sensor
    
    # implemented by child sensor class
    def detect(self):
        
        raise NotImplementedError
    
    def _get_chunk_sizes(self):

        assert isinstance(self.acquisition_rate, (float, int))
        
        # chunk to 1MB chunks (recommendation of zarr docs)
        self.time_chunk = (math.ceil(10 ** 6 / (math.prod(self.shape) * 8)),)     # TODO: what type are we using? Always float/int64?
        
        # if we are handling one/multiple 1D timeseries columns, chunk down each column separately (allow for selective column reads)
        if len(self.shape) < 1:
            self.data_chunk = self.time_chunk
        
        # if we are handling 2D+ data, don't bother to chunk in dimensions other than time
        else:
            self.data_chunk = self.time_chunk + self.shape

        self.buffer_len = min(math.ceil(self.time_chunk[0] / 10), math.ceil(self.acquisition_rate * .5)) # buffer is the lesser of: 10% of a chunk size; amount of data collected in 5 seconds
        self.buffer_len = 2 ** math.floor(np.log2(self.buffer_len)) # lower-bounding power of 2

        logger.info(f'time_chunk: {self.time_chunk}\ndata_chunk: {self.data_chunk}\nbuffer_len: {self.buffer_len}')
    
    def initialize(self, zarr_group = None):
        
        self._get_chunk_sizes() # needed even when we aren't writing data to define self.buffer_len

        # init zarr group. if zarr_group is none, don't write any data
        if zarr_group is not None:
            
            self.group = zarr_group
            self.time = self.group.create_array(name = 'time', 
                                                shape = (0,), 
                                                chunks = self.time_chunk, 
                                                dimension_names = ('time',),
                                                dtype = np.uint64)
            
            self.data = self.group.create_array(name = 'data', 
                                                shape = (0,) + self.shape, 
                                                chunks = self.data_chunk, 
                                                dimension_names = ('time',) + self.columns,
                                                dtype = self.dtype)
            
            self.group.attrs['acquisition_rate'] = self.acquisition_rate
        
        # implement sensor-specific initialization here. include metadata
    
    def start_collection(self):
        
        # check that collection is ready
        if not self.flag_initialized:

            logger.warning(f"{self.name} was not initialized before collection start.")
            
            try:
                self.initialize()
            except Exception as e:
                logger.error(e)
        
        with self.lock:
            self.flag_is_collecting = True # we aren't really collecting until we start the threads, but we were seeing a race condition on collection_thread()'s while condition

        # only write if desired
        if self.group is not None:
            self.writer_thread = threading.Thread(target = self.writing_thread, name = self.name + '_writer')
            self.writer_thread.start()
        
        # start threaded collection
        self.collector_thread = threading.Thread(target = self.collection_thread, name = self.name + '_collector')
        self.collector_thread.start()
    
    # implemented by child sensor class
    def collection_thread(self):

        assert isinstance(self.buffer_len, int)

        with self.lock:
            flag_is_collecting = self.flag_is_collecting
            
        while flag_is_collecting:

            buffer      = np.zeros((self.buffer_len,) + self.shape, dtype = self.dtype)
            buffer_time = np.zeros((self.buffer_len,))

            for i in range(self.buffer_len):

                self.sample_sensor()
                buffer[i]      = self.sample
                buffer_time[i] = self.sample_time

            if self.group is not None:
                self.buffers.put(buffer)
                self.buffer_times.put(buffer_time)
                
            with self.lock:
                flag_is_collecting = self.flag_is_collecting
                
        return

    def sample_sensor(self):
        """
        Actually get a sample from the sensor. Implemented by child classes. Should update self.sample with a new sample and self.time with a new timestamp
        """

        raise NotImplementedError
    
    def writing_thread(self):
        
        time.sleep(.5)

        assert isinstance(self.collector_thread, threading.Thread)

        while self.collector_thread.is_alive():

            while not self.buffers.empty():

                self.data.append(self.buffers.get())
                self.time.append(self.buffer_times.get())
                
    
    # stop threaded process
    def stop_collection(self):

        assert isinstance(self.collector_thread, threading.Thread)
        
        if self.group is not None:
            assert isinstance(self.writer_thread   , threading.Thread)

        with self.lock:
            flag_is_collecting = self.flag_is_collecting

        if self.flag_is_collecting:

            with self.lock:
                self.flag_is_collecting = False

            self.collector_thread.join()
            
            if self.group is not None:
                self.writer_thread.join()

        else:
            raise Exception(f"{self.name} is not collecting. It cannot be stopped!")

class BufferedSensor(BaseSensor):

    def __init__(self):

        super(BufferedSensor, self).__init__()

        del self.sample
        del self.sample_time

        self.buffer = None
        self.buffer_time = None


    def collection_thread(self):

        assert isinstance(self.buffer_len, int)

        with self.lock:
            flag_is_collecting = self.flag_is_collecting
            
        while flag_is_collecting:

            # placement of buffers into buffer should be handled by sample_sensor(), which now collects entire buffers at a time from a sensor
            self.sample_sensor()
                
            with self.lock:
                flag_is_collecting = self.flag_is_collecting
                
        return

#class XIR1800(BaseSensor):

    


