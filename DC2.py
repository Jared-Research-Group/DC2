# generic imports
import os
from datetime import datetime
import keyboard
import psutil  
import zarr

# DC2 imports
import DC2_helpers

import thermocouple
import robot
import microphone

# --------------------------------------

logger = DC2_helpers.init_logger(__name__)

sensor_list = [thermocouple.ThermocoupleDAQ, robot.RSI, microphone.Microphone] # list of all sensors we will search for. To use more than one of the same sensor type, add a duplicate to the list
        
class DataCollectionSystem:
    
    def __init__(self, file_prefix = 'data_collection'):
        
        self.output_path = None
        self.sensors = set()
        self.file_prefix = file_prefix
        
    def test_connection(self):
        
        logger.debug('Testing sensor connections...')
        
        for expected_sensor in sensor_list:
            
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

                logger.error(e)
                del sensor

        # return value tells us if any sensors successfully initialized
        return bool(self.sensors)

    def start_collection(self):

        logger.debug('Starting collection...')

        for sensor in self.sensors:

            try: sensor.start_collection()

            except Exception as e: logger.error(e)
        

    def stop_collection(self):

        logger.debug('Stopping collection...')

        for sensor in self.sensors:

            try: sensor.stop_collection()

            except Exception as e: logger.error(e)

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

        if keyboard.is_pressed('q'):
            system.stop_collection()
            break

    return

if __name__ == "__main__":
    main()