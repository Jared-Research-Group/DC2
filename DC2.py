# generic imports
import os
from datetime import datetime
import keyboard
import psutil  
import zarr
import threading
import yaml

# DC2 imports
import DC2_helpers

import thermocouple
import robot
import microphone
import lembox
import FLIR
import xiris

# --------------------------------------

logger = DC2_helpers.init_logger(__name__)

sensor_list = {'thermocouple':thermocouple.ThermocoupleDAQ, 
               'robot': robot.RSI, 
               'microphone': microphone.Microphone, 
               'lembox': lembox.LEMBox, 
               'flir': FLIR.FLIR, 
               'xiris': xiris.Xiris,
               } # list of all sensors we will search for. To use more than one of the same sensor type, add a duplicate to the list
        
class DataCollectionSystem:
    
    def __init__(self, file_prefix = 'data_collection'):
        
        self.output_path = None
        self.sensors = set()
        self.file_prefix = file_prefix
        
        self.expected_sensors = []
        
        with open('config.yaml', 'r') as f:
            data = yaml.safe_load(f)
            
            self.expected_sensors = [sensor_list[sensor] for sensor in data['allowed_sensors']]
        
    def test_connection(self):
        
        logger.debug('Testing sensor connections...')
        
        for expected_sensor in self.expected_sensors:
            
            sensor = expected_sensor()
            
            try:
                
                sensor.detect()
                self.sensors.add(sensor)
                
            except Exception as e:

                logger.warning(e)
                del sensor

        # return value tells us if any sensors are connected
        return bool(self.sensors)
                
    def initialize_collection(self):
        
        logger.debug('Initializing collection...')
        
        self.output_path = DC2_helpers.select_folder() / (self.file_prefix + datetime.now().strftime('%Y%m%d_%H%M%S') + '.zarr')
        
        store = zarr.storage.LocalStore(self.output_path) # type: ignore
        self.zarr_root = zarr.group(store=store)
        
        for sensor in self.sensors:
            
            group = self.zarr_root.create_group(name = sensor.name)
            
            try: sensor.initialize(group)
                
            except Exception as e:

                logger.error(sensor.name + ': ' + str(e))
                del sensor

        # return value tells us if any sensors successfully initialized
        return bool(self.sensors)

    def start_collection(self):

        logger.debug('Starting collection...')

        for sensor in self.sensors:

            try: sensor.start_collection()

            except Exception as e: logger.error(str(e))
        

    def stop_collection(self):

        logger.info('Stopping collection...')
        
        stop_threads = []

        for sensor in self.sensors:

            try: 
                
                stop_threads.append(threading.Thread(target = sensor.stop_collection, name = sensor.name + '_stopper_thread'))
                stop_threads[-1].start()

            except Exception as e: logger.error(str(e))
            
        for thread in stop_threads:
            thread.join()


def main():

    # Lower main process priority
    try:
        process = psutil.Process(os.getpid())
        process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == 'nt' else 10)
    except Exception:
        pass

    # Initialize data collection system
    system = DataCollectionSystem()
    
    # Verify connected sensors
    if not system.test_connection():
        logger.critical("No sensors detected. Please check connections.")
        return

    print("\nPress Enter to begin setup...")
    input()
    
    # Prepare the system
    if not system.initialize_collection():
        return
        
    # Wait for user to start collection
    print("\nSystem ready! Press Enter to start data collection...")
    input()
    
    # Start data collection
    system.start_collection()

    while True:

        try:
            if keyboard.is_pressed('q'):
                system.stop_collection()
                break
            
        except KeyboardInterrupt:
            system.stop_collection()
            break

    return

if __name__ == "__main__":
    main()