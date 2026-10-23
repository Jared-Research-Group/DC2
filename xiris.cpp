#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include <string>
#include <queue>
#include <vector>
#include <mutex>
#include <cmath>
#include <tuple>
#include "json.hpp"

#include <iostream>
#include <iomanip>
#include <typeinfo>

#include <windows.h>
#include "WeldSDK/WeldCamera.h"
#include "WeldSDK/CameraDetector.h"
#include "XImageLib/Image/CRawImage.h"

namespace nb = nanobind;
using namespace nb::literals;

// we need a special thread-safe queue type because we will be reading from MyXirisCamera's frameBuffer queue in this thread while the SDK writes to the queue
template <typename T>
class ThreadSafeQueue {
    private:
        std::queue<T> q;
        std::mutex mtx;
        std::condition_variable cv;

    public:

        ThreadSafeQueue() {}

        bool empty() {

            std::lock_guard<std::mutex> lock(mtx);
            return q.empty();
        }

        T pop() {

            std::unique_lock<std::mutex> lock(mtx);

            cv.wait_for(lock, std::chrono::milliseconds(250), [this] { return !q.empty(); });
            T val = std::move(q.front());
            q.pop();

            return val;
        }

        void push(T element) {

            std::lock_guard<std::mutex> lock(mtx);
            q.push(std::move(element));
        }
};

class MyXirisCamera:
    // multiple inheritance. MyXirisCamera is a child of both WeldCamera and CameraEventSink
    public WeldSDK::WeldCamera,
    public WeldSDK::CameraEventSink
{

    private:
        WeldSDK::CameraClass cameraType;
        bool isReady;

    public: 

        std::string ipAddress;
        bool isRecording = false;
        ThreadSafeQueue<std::uint64_t> timeBuffer;
        ThreadSafeQueue<std::vector<uint16_t>> frameBuffer;
        ThreadSafeQueue<std::string> metaBuffer;

        MyXirisCamera(const std::string ip, WeldSDK::CameraClass type = WeldSDK::CameraClass::XVT1800, bool recordRaw = true, bool recordPng = false):
            WeldSDK::WeldCamera(),
            ipAddress(ip),
            cameraType(type)
        {
            AttachEventSink(this); // events from the connected camera are handled by MyXirisCamera's callback functions
        }

        // deconstructor kills event sink thread
        virtual ~MyXirisCamera() {

            DetachEventSink(this);
        }

        // hide Connect's arguments under the hood
        bool ConnectCamera() {
            return Connect(ipAddress, cameraType);
        }

        // set a flag once the camera is connected and ready to start recording
        virtual void OnCameraReady(WeldSDK::CameraReadyEventArgs args) override {

            isReady = true;

            return;
        }

        // leftover from older version. Do we ever change streaming state
        virtual void OnStreamingStateChanged(WeldSDK::CameraStreamingEventArgs args) override {

            if (args.IsStreaming) {
                if (args.IsPaused) {
                    std::cout << "Camera " << ipAddress << " is paused.\n";
                }
                else {
                    std::cout << "Camera " << ipAddress << " is streaming.\n";
                }
            }
            else {
                std::cout << "Camera " << ipAddress << " is stopped.\n";
            }

            return;
        }

        // what we do when a new frame is collected
        virtual void OnBufferReady(WeldSDK::BufferReadyEventArgs args) override {

            if (isRecording) {
                try {

                    // image in args becomes CRawImage
                    XirisCommon::XImage *img = args.RawImage;

                    int img_size = img->height * img->width * 2;

                    // initialize a vector of bytes of correct size ot hold the image we found
                    std::vector<uint16_t> dat(img_size / 2);

                    // copy our image into the byte array
                    std::memcpy(dat.data(), img->data, img_size);     // img.data is NOT the byte string we get when we save a frame. we need to find the metadata too

                    // stick our image into the frame queue
                    frameBuffer.push(dat);
                    timeBuffer.push((uint64_t)(img->timestamp * std::pow(10, 9)));

                    metaBuffer.push(img->metaData.dump());

                } 
                catch (const std::exception& e) {
                    std::cout << "Error saving frame: " << e.what() << std::endl;
                }
            }

            return;
        }
        
        // is this ever used?
        virtual void OnTraceMessage(WeldSDK::TraceMessageEventArgs args) override {

            std::cout << "Camera " << ipAddress << " Message: " << args.Message << "\n";
            return;
        }

};

// wrapper for a CameraDetectorEventSink + function returning shared ptr to a MyXirisCamera object
class SimpleDetector: public WeldSDK::CameraDetectorEventSink {

    private:
        WeldSDK::CameraClass cameraType;            // camera model
        WeldSDK::CameraDetector* detector;           // detector obj
        std::mutex cameraMtx;                       // mutex (thread lock)
        std::condition_variable waitForCameraCv;    // condition check for mutex
        std::shared_ptr<MyXirisCamera> camera;        // discovered camera

    public:

        SimpleDetector(WeldSDK::CameraClass type = WeldSDK::CameraClass::XVT1800) {

            detector = WeldSDK::CameraDetector::GetInstance();  // we cannot call the constructor of CameraDetector directly, otherwise we would make SimpleDetector a child of CameraDetector
            cameraType = type;                                  // Class of camera we plan to detect
            detector->AttachEventSink(this);                    // link detector to this class's OnCameraDetected
        }
    
        // callback for when SDK thread enumerates a camera
        virtual void OnCameraDetected(WeldSDK::CameraEventArgs args) {

            if (args.CanConnect) {
                if (args.CameraType == cameraType) {    // if it's the camera we are looking for

                    // lock makes the main program wait while we detect cameras
                    std::lock_guard<std::mutex> lk(cameraMtx);

                    if (camera == nullptr) {
                        camera = std::make_shared<MyXirisCamera>(args.CameraIPAddress, args.CameraType);    // construct a camera object from detected camera
                        waitForCameraCv.notify_one();   // unlock main program thread
                    }

                }
            }
        }

        // callable detection function. returns ip address of camera
        std::string DetectCamera(int timeout) {

            // lock forces this function to wait until a camera is detected
            std::unique_lock<std::mutex> lk(cameraMtx);

            waitForCameraCv.wait_for(lk, 
                                     std::chrono::seconds(timeout),
                                     [this] { return camera != nullptr; }
                                    ); // wait until lambda function returns true, or timeout is reached
            lk.unlock();

            detector->StopMonitoring();
            detector->DetachEventSink(this);
            
            // return ip address if camera was detected, else return -1
            // this way, we don't hold on to a camera object that we don't actually want.
            return camera != nullptr ? camera->ipAddress : "-1";
        }
};

// entry point (is this the right term?) for nanobind to use SimpleDetector. Discovers a camera' ip
std::string DetectXirisCamera(int timeout = 10) {
    SimpleDetector* detector = new SimpleDetector(WeldSDK::CameraClass::XVT1800);

    std::string ip = detector->DetectCamera(timeout);

    delete detector;
    return ip;
}

// library holds constant reference to a camera object internally
std::shared_ptr<MyXirisCamera> camera;

// need buffer initialization for storing recorded frames!!!!!!!!!
// connect to camera and set user's desired settings.
std::pair<bool, std::string> InitXirisCamera(std::string ipAddress, float frame_rate = -1, std::vector<int> AoI = {0, 512, 0, 640}) { // AOI: {left, right, top, bottom}
    std::string msg = "";

    camera = std::make_shared<MyXirisCamera>(ipAddress);

    // get our camera
    if (!camera->ConnectCamera()) {

        msg = "Camera connection failed";
    }

    /*
    // immediately pause the camera stream. We don't want to fill tons of buffers before real data collection starts
    if (!camera->Pause()) {

        msg = "Camera Pause on init failed";
    }
    */ 

    // set frame count to 0. Unclear if this will increment during the pause (same frame is still streamed). TODO: investigate
    if (!camera->ResetFrameCounter()) {

        msg = "Camera frame counter reset on init failed";
    }

    if (!camera->setPixelDepth(WeldSDK::PixelDepths::Bpp14)) {

        msg = "Camera pixel depth setting failed";
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    if (!camera->setFFCEnabled(true)) {

        msg = "Camera set flat field correction failed";
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    if (!camera->setShutterMode(WeldSDK::ShutterModes::Global)) {

        msg = "Camera set shutter mode failed";
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    //if (!camera->setAutoGainMode(WeldSDK::AutoControlModes::Continuous)) {
    if (!camera->setGSGainMode(WeldSDK::GlobalShutterGainMode::HighGain)) {

        msg = "Camera set auto gain mode failed";
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    if (frame_rate == -1.) {
        if (!camera->setGSFrameRateLimitEnabled(false)) {

            msg = "Camera set unlimited frame rate failed";
        }
    } else {

        if (!camera->setGSFrameRateLimit(frame_rate) || !camera->setGSFrameRateLimitEnabled(true)) {

            msg = "Camera set frame rate limit failed";
        }
    }

    XirisCommon::Rect AoI_rect = XirisCommon::Rect::Rect(AoI[2], AoI[0], AoI[3], AoI[1]);

    if (!camera->setAOI(AoI_rect)) {

        msg = "Camera set AoI failed";
    }

    if (msg != "") {
        return std::make_pair(false, msg);
    } else {
        return std::make_pair(true, msg);
    }

}

// start the camera recording. do we need a global start timestamp here?
std::pair<bool, std::string> XirisStartRecording() {
    std::string msg = "";

    if (camera->isRecording) {
        msg = "Camera already recording!";
        return std::make_pair(false, msg);
    } else {
        camera->isRecording = true;
        camera->ResetTimeStamps();
        camera->Start();

    }

    return std::make_pair(true, msg);
}

std::tuple<std::vector<uint16_t>, uint64_t, std::string> XirisGetFrame() {
    if (!camera->frameBuffer.empty()) {

        std::vector<uint16_t> img = camera->frameBuffer.pop();
        uint64_t time = camera->timeBuffer.pop();
        std::string meta = camera->metaBuffer.pop();

        return std::tuple(img, time, meta);

    } else {

        std::vector<uint16_t> empty_vector;
        return std::tuple(empty_vector, 0, "");
    }
}

bool XirisStopRecording() {

    std::cout << "starting stop..." << std::endl;

    camera->BeginStop();
    bool stopped = camera->WaitForStopComplete();

    std::cout << "stop complete..." << std::endl;

    return stopped;

}

bool XirisFrameBufferEmpty() {

    return camera->frameBuffer.empty();
}

void XirisDeleteCamera() {
    delete &camera;
}

// define python bindings
NB_MODULE(xiris_bindings, m) {
    m.def("detectCamera", &DetectXirisCamera, "timeout"_a = 10);
    m.def("initCamera", &InitXirisCamera, "ipAddress"_a, "frame_rate"_a = -1, "AoI"_a = std::vector<int> {0, 512, 0, 640});
    m.def("startCamera", &XirisStartRecording);
    m.def("sampleCamera", &XirisGetFrame);
    m.def("stopCamera", &XirisStopRecording);
    m.def("cameraBufferIsEmpty", &XirisFrameBufferEmpty);
    m.def("deleteCamera", &XirisDeleteCamera);
}
