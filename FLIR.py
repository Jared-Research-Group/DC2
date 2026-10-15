import PySpin

import sensors
import DC2_helpers

logger = DC2_helpers.init_logger(__name__)

class FLIR(sensors.BaseSensor):

    def __init__(self, IRFormat = 'RADIOMETRIC'):

        super().__init__()

        self.name = 'FLIR'
        self.acquisition_rate = 30 # Hz
        self.shape = (348, 464)
        self.columns = ('FLIR')

        self.system = PySpin.System.GetInstance()
        self.camera = None
        self.IRFormat = IRFormat # can be 'RADIOMETRIC', 'TemperatureLinear10mK', or 'TemperatureLinear100mK'

    def detect(self):

        try:

            cam_list = self.system.GetCameras()

            camera_detected = cam_list.GetSize() > 0 # did we detect at least one camera?

            cam_list.Clear()
            self.system.ReleaseInstance()

            if not camera_detected:
                raise DC2_helpers.SensorNotConnectedError(sensor = self.name)
            
        except Exception as e:
            raise Exception(f"FLIR camera connection error: {e}")

    def initialize(self, zarr_group):

        super(FLIR, self).initialize(zarr_group)

        cam_list = self.system.GetCameras()

        if cam_list.GetSize() == 0:

            raise Exception('No FLIR camera detected')
            return

        self.camera = cam_list[0] # If we see interference from a 2nd camera, we can use TLDeviceNodeMap to read SNs of individual cameras
        self.camera.Init()

        stream_nodemap = self.camera.GetTLStreamNodeMap()
        device_nodemap = self.camera.GetTLDeviceNodeMap()
        nodemap        = self.camera.GetNodeMap()

        stream_nodemap_settings = {
            'StreamBufferHandlingMode': 'NewestOnly',
        }

        nodemap_settings = {
            'PixelFormat': 'Mono16',
            'AcquisitionMode': 'Continuous',
            'IRFormat': self.IRFormat,
        }

        settings = {
            stream_nodemap: stream_nodemap_settings,
            nodemap: nodemap_settings
        }

        # iterate over nodemaps, settings dicts
        for map, list in settings.items():

            # iterate over nodes, settings in settings lists
            for node, setting in list.items():

                # set node settings to desired values

                if not PySpin.IsWritable(map.GetNode(node)):
                    raise Exception(f"FLIR node {node} is not writable")

                map.GetNode(node).SetIntValue(map.GetNode(node).GetEntryByName(setting).GetValue())


        radiometric_calibration_values = {
            'R',       # calibration constant
            'B',       # calibration constant
            'F',       # calibration constant
            'X',       # scaling factor for attenuation
            'alpha1',  # attenation for atmosphaere without water vapor
            'alpha2',  # attenuation for atmosphere without water vapor
            'beta1',   # attenuation for water vapor
            'beta2',   # attenuation for water vapor
            'J1',      # gain
            'J0',      # offset
            }

        for value in radiometric_calibration_values:
            zarr_group['radiometric_calibration_values'][value] = nodemap.GetNode(value).GetValue()

        environment_values = {
            'Emiss': 0.97,
            'TRefl': 293.15,
            'TAtm': 293.15,
            'TAtmC': 20,
            'Humidity': 0.55,
            'Dist': 2,
            'ExtOpticsTransmission': 1,
            'ExtOpticsTemp': 293.15,
            }

        zarr_group['environment_values'] = environment_values


        self.flag_initialized = True


    def collection_thread(self):

        self.camera.BeginAcquisition()

        super(FLIR, self).collection_thread()

    def sample_sensor(self):

        img = self.camera.GetNextImage()
        if img.IsIncomplete():
            raise Exception(f'FLIR: Image incomplete with image status {img.GetImageStatus()}.')

        self.sample[:] = img.GetNDArray()
        self.sample_time[:] = img.GetTimeStamp()

        img.Release()

    def stop_collection(self):

        super(FLIR, self).stop_collection()

        self.camera.uninitialize()
        self.system.ReleaseInstance()