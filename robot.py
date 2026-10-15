import subprocess
import os
import socket
import time
import xml.etree.ElementTree as ET

import DC2_helpers
import sensors

logger = DC2_helpers.init_logger(__name__)

class RSI(sensors.BaseSensor):

    def __init__(self, recv_ip = '192.168.1.25', send_ip = '192.168.1.147', send_port = 53453, recv_port = 59152, flag_send = False, send_cols = [], send_fns = []):

        super(RSI, self).__init__()

        self.name             = 'RSI'
        self.acquisition_rate = 100 # Hz
        self.shape            = tuple()
        self.columns          = tuple()
        self.dtype            = 'U500'

        self.recv_ip   = recv_ip # expected robot IP
        self.send_port = send_port
        self.recv_port = recv_port

        self.flag_send = flag_send # are we doing two-way communication with the robot?
        self.send_ip   = send_ip # ip to send responses to
        self.send_cols = send_cols # if we are doing two_way communcation, this is a tuple of column names we plan to send
        self.send_fns  = send_fns # if we are doing two-way communication, this is a list of functions used to generate our responses to the robot
        
        self.socket = None

    def detect(self):

        param = '-n' if os.sys.platform.lower() == 'win32' else '-c' # type: ignore
        timeout_param = '-w' if os.sys.platform.lower() == 'win32' else '-W' # type: ignore

        result = subprocess.run(f"ping {param} 1 {timeout_param} 1 {self.recv_ip}", capture_output = True, text = True)

        if result.returncode != 0:
            raise DC2_helpers.SensorNotConnectedError(sensor = self.name)

    def initialize(self, zarr_group):

        try:
            super(RSI, self).initialize(zarr_group)

            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if self.flag_send: self.socket.connect((self.send_ip, self.send_port))   # connect to robot for UDP send
            
            self.socket.bind((self.recv_ip, self.recv_port))
            self.socket.settimeout(0.1)
            logger.debug(f"{self.name} listening on {self.recv_ip}:{self.recv_port}")

            self.flag_initialized = True

        except Exception as e:

            logger.error(f"Error initializing RSI: {e}")

    def sample_sensor(self):

        try:
            
            sample_start = time.time_ns()
            data_time = sample_start

            while data_time - sample_start < 1e9:

                data = self.socket.recv(1024) # type: ignore
                data_time = time.time_ns() # Get timestamp immediately after receiving data TODO: RSI needs to report a send time instead of us writing a read time

                data_str = data.decode('utf-8') # store recieved string as str, not byte array

                if data_str != self.sample:

                    self.sample = data_str
                    self.sample_time = data_time
                    
                    break

            if self.flag_send: 

                root = ET.fromstring(data_str) # convert recieved string to xml tree object
                ipoc = root.find('IPOC') # recover IPOC (KUKA's internal timer) from recieved xml tree. This field needs to be sent in a return message to the robot

                # construct our XML response with the TreeBuilder class. I have assumed that the robot wants to see <root><IPOC></IPOC>...</root>. This may take testing/manual deepdive to confirm
                response = ET.TreeBuilder()
                response.start(root.tag, root.attrib) # add root
                response.start(ipoc.tag, ipoc.attrib) # type: ignore ; add child
                response.data(str(ipoc.text)) # type: ignore ; add child data
                response.end(ipoc.tag) # type: ignore ; we must close elements in hierarchical order

                # build arbitrary response values
                for tag, fn in zip(self.send_cols, self.send_fns):
                    response.start(tag) # type: ignore
                    response.data(str(fn())) # TODO: what arguments might a general function need here?
                    response.end(tag)

                response.end(root.tag)
                resp_root = response.close() # TreeBuilder returns root element

                response = ET.tostring(resp_root, encoding='utf-8')
                logger.debug(response) # PRINT FOR DEBUG
                self.socket.send(response) # type: ignore ; send the constructed response string to the KUKA over socket
                
        except socket.timeout:
            pass
        except Exception as e:
            print(f"Error receiving data: {e}")

    def stop_collection(self):
       
       super().stop_collection()

       assert self.socket is socket.SocketType

       self.socket.close()

    def __del__(self):

        if self.socket is not None:
            self.socket.close()

if __name__ == '__main__':

    DC2_helpers.single_sensor_display(RSI)