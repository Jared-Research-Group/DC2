import logging
import pathlib
import tkinter as tk
from tkinter import filedialog
import keyboard
from datetime import datetime
import numpy as np

def init_logger(script_name):
    
    logging.basicConfig(level = logging.DEBUG)
    logging.getLogger().handlers.clear()
    
    logger = logging.getLogger(script_name)
    
    if not logger.handlers:
        
        # log format
        formatter = logging.Formatter('%(asctime)s - %(name)20s - %(levelname)s - %(message)s')

        # handler for output to log file. This logger is the most verbose logger possible, capturing all debug statements.
        file_handler = logging.FileHandler('DC2.log')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)


        # handler for output to terminal. This logger is verbose if associated with the file the user is running, otherwise it is less verbose.
        terminal_handler = logging.StreamHandler()

        if script_name == '__main__':
            terminal_handler.setLevel(logging.INFO)
        else:
            terminal_handler.setLevel(logging.WARNING)

        terminal_handler.setFormatter(formatter)

        logger.addHandler(terminal_handler)
        logger.addHandler(file_handler)

    # When the user runs a file, this line places a break in the logfile (makes reading the log file easier).
    if script_name == '__main__':
        logger.info('\n\nNew process starting...\n')

    return logger

def select_folder(title='Select Build Folder'):
    
    # setup initial file location
    init_dir = pathlib.Path.home()
    if (init_dir / 'Data').is_dir():
        init_dir /= 'Data'

    root = tk.Tk()
    root.wm_attributes('-topmost', 1)
    root.withdraw()

    path = tk.filedialog.askdirectory( # type: ignore
        title=title,
        initialdir = init_dir,
        parent=root
    )

    return pathlib.Path(path)

def single_sensor_display(sensor_obj, sensor_args = {}):

    import sensors

    class printing_sensor(sensor_obj):

        def __init__(self, sensor_args):
            super(printing_sensor, self).__init__(**sensor_args)

        if issubclass(sensor_obj, sensors.BufferedSensor):
            def sample_sensor(self, *args, **kwargs):

                ret = super(printing_sensor, self).sample_sensor(*args, **kwargs)

                if self.buffer.size > 0:
                    # while self.buffer_time holds a list of samples, index another layer into self.buffer / self.buffer_time
                    #while not type(self.buffer_time) in [np.uint64, int]:
                        #self.buffer_time = self.buffer_time[-1]
                        #self.buffer      = self.buffer[-1]
                        
                    #self.buffer_time = self.buffer_time[-1]
                    #self.buffer = self.buffer[:, -1]

                    #print(f'{sensor_obj.__name__}\ttime: {datetime.fromtimestamp(self.buffer_time * 1e-9)}\tvalue: {str(self.buffer):<20}', end='\r') # flush=True)
                    
                    print(self.buffer)
                
                return ret

        else:
            def sample_sensor(self, *args, **kwargs):

                ret = super(printing_sensor, self).sample_sensor(*args, **kwargs)
                
                while not type(self.sample_time) in [np.uint64, int]:
                    self.sample_time = self.sample_time[-1]
                    self.sample      = self.sample[-1]

                if not isinstance(self.sample, bytes): print(f'{sensor_obj.__name__}\ttime: {datetime.fromtimestamp(self.sample_time * 1e-9)}\tvalue: {self.sample:<20}', end='\r') # flush=True)
                else:                                  print(f'{sensor_obj.__name__}\ttime: {datetime.fromtimestamp(self.sample_time * 1e-9)}\tvalue: {self.sample}', end='\r')
                
                return ret

    logger = logging.getLogger('__main__')
    sensor = printing_sensor(sensor_args)

    try: 
        sensor.detect()
    except SensorNotConnectedError:
        
        logger.critical(f'{sensor.name} not found. Aborting...')
        return

    sensor.initialize(zarr_group = None)
    sensor.start_collection()

    while True:
        
        try:
            if keyboard.is_pressed('q'):
                sensor.stop_collection()
                break
            
        except KeyboardInterrupt:
            sensor.stop_collection()
            break


class SensorNotConnectedError(Exception):
    """
    Exception raised when a sensor fails initial connection check
    """
    
    def __init__(self, message = None, sensor = None):

        if message is None:
            message = f"{sensor} failed to connect."
            
        super().__init__(message)
        
        