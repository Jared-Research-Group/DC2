# generic imports
import time

# hardware-specific imports
import nidaqmx

# project imports
import DC2_helpers
import sensors

logger = DC2_helpers.init_logger(__name__)

class ThermocoupleDAQ(sensors.BaseSensor):
    
    def __init__(self, device_name = 'cDAQ1Mod1'):
        
       super(ThermocoupleDAQ, self).__init__()

       self.name             = 'ThermocoupleDAQ'
       self.acquisition_rate = 3.5 # Hz
       self.shape            = (4,) # each sample of the sensor produces 4 values
       self.columns          = ('sample',)

       self.device_name = device_name
       self.task = None

    def detect(self):

        system = nidaqmx.system.System.local() # type: ignore

        if self.device_name not in system.devices:
            raise DC2_helpers.SensorNotConnectedError(sensor = self.name)

    def initialize(self, zarr_group):

        super(ThermocoupleDAQ, self).initialize(zarr_group)

        try:

            self.task = nidaqmx.Task()

            for i in range(4):

                channel = f"{self.device_name}/ai{i}"

                self.task.ai_channels.add_ai_thrmcpl_chan(channel,
                                                          name_to_assign_to_channel = f"Thermocouple_{i}",
                                                          thermocouple_type = nidaqmx.constants.ThermocoupleType.K, # type: ignore
                                                          units = nidaqmx.constants.TemperatureUnits.DEG_C) # type: ignore
            
            self.task.timing.cfg_samp_clk_timing(rate = self.acquisition_rate,
                                                 sample_mode = nidaqmx.constants.AcquisitionType.CONTINUOUS, # type: ignore
                                                 samps_per_chan = 1)

            self.flag_initialized = True

        except Exception as e:

            logger.error(f"Error initializing ThermocoupleDAQ: {e}")

    def sample_sensor(self):

        assert isinstance(self.task, nidaqmx.Task)

        try:
            self.sample = self.task.read()
            self.sample_time = time.time_ns()
            
        except nidaqmx.errors.Error as e: # type: ignore
            logger.critical(f"Error reading thermocouple: {e}")

    def stop_collection(self):
        super().stop_collection()

        assert isinstance(self.task, nidaqmx.Task)

        self.task.close()
        self.task = None

    def __del__(self):

        if self.task is not None:
            self.task.close()

if __name__ == '__main__':

    DC2_helpers.single_sensor_display(ThermocoupleDAQ)