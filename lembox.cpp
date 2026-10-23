#include <nanobind/nanobind.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/vector.h>
#include <nanobind/stl/string.h>

#include <vector>
#include <string>

#include <windows.h>
#include <olmem.h>
#include <olerrors.h>
#include <oldaapi.h>

namespace nb = nanobind;
using namespace nb::literals;

// info about the connected board - must come before other structures
typedef struct tag_board {
   HDEV  hdrvr;        // device/driver handle
   HDASS hdass;        // data acquisition sub system handle
   ECODE status;       // board error status
   char name[MAX_BOARD_NAME_LENGTH];  // human-readable string for board name
   char entry[MAX_BOARD_NAME_LENGTH]; // non-human-readable string for board name
} BOARD;

typedef BOARD* LPBOARD;  // LPBOARD is a pointer to a board struct TODO: is this too abstract?

#define NUM_CHANNELS 2
#define VOLTAGE_CHANNEL 0
#define CURRENT_CHANNEL 1
#define NUM_BUFFERS 64

#define EPOCH_DIFF_100NS 116444736000000000ULL // number of 100NS between FILETIME and unix time starts

static BOARD board;
static HBUF* buffers = NULL;

// called for each detected board in a system. Currently, if we see a board, we stop enumeration.
// for multiple connected boards, you would need to do something different.
BOOL CALLBACK GetDriver(LPSTR lpszName, LPSTR lpszEntry, LPARAM lParam) { // enumerated human-readable board name, enumerated driver entry string (non-human-readable id), LPBOARD pointer as abstract pointer
    LPBOARD lpboard = (LPBOARD)(LPVOID)lParam; // convert board pointer back to LPBOARD pointer (must be arbitrary pointer as it passes through olDaEnumBoards)
    
    // store name, entry
    lstrcpyn(lpboard->name , lpszName , MAX_BOARD_NAME_LENGTH - 1);
    lstrcpyn(lpboard->entry, lpszEntry, MAX_BOARD_NAME_LENGTH - 1);

    lpboard->status = olDaInitialize(lpszName, &lpboard->hdrvr); // try to connect to this board

    // if board.hdrvr is not NULL, we are connected to a board and can stop enumeration
    if (lpboard->hdrvr != NULL)
        return FALSE;    // false to stop enumerating
    else                      
        return TRUE;     // true to continue
}

std::pair<BOOL, std::string> detectBoard() {
    std::string msg = "";

    // enumerate all detected boards. Each seen board is sent to the GetDriver callback. Write info of the
    // first board we successfully connect to into board.
    if (olDaEnumBoards(GetDriver, (LPARAM)(LPBOARD)&board) != OLNOERROR) {

        // if we get an enumeration error, return False

        msg = "Failed to enumerate boards";
        return std::make_pair(FALSE, msg);
    }

    // if we didn't connect to any boards, return False
    if (board.hdrvr == NULL) {
        msg = "No DT boards found";
        return std::make_pair(FALSE, msg);
    }

    // success
    return std::make_pair(TRUE, msg);
}

std::pair<BOOL, std::string> configureADC(DBL freq) { // default 20 kHz sample rate
    std::string msg = "";

    // check that A/D subsystem exists
    UINT numberADs = 0;
    if (olDaGetDevCaps(board.hdrvr, OLDC_ADELEMENTS, &numberADs) != OLNOERROR) {
        msg = "Failed to get device capabilities";
        return std::make_pair(FALSE, msg);
    }

    // get A/D subsystem
    if (olDaGetDASS(board.hdrvr, OLSS_AD, 0, &board.hdass) != OLNOERROR) {
        msg = "Failed to get ADC subsystem";
        return std::make_pair(FALSE, msg);
    }

    // Configure ADC
    ECODE status;
    
    if ((status = olDaSetRange(board.hdass, 10.0, -10.0)) != OLNOERROR ||
        (status = olDaSetDataFlow(board.hdass, OL_DF_CONTINUOUS)) != OLNOERROR ||
        (status = olDaSetWrapMode(board.hdass, OL_WRP_MULTIPLE)) != OLNOERROR ||
        (status = olDaSetClockSource(board.hdass, OL_CLK_INTERNAL)) != OLNOERROR ||
        (status = olDaSetEncoding(board.hdass, OL_ENC_BINARY)) != OLNOERROR ||
        (status = olDaSetClockFrequency(board.hdass, freq)) != OLNOERROR ||
        (status = olDaSetChannelListSize(board.hdass, NUM_CHANNELS)) != OLNOERROR || // swapped position w/ entry calls
        (status = olDaSetChannelListEntry(board.hdass, 0, VOLTAGE_CHANNEL)) != OLNOERROR ||
        (status = olDaSetChannelListEntry(board.hdass, 1, CURRENT_CHANNEL)) != OLNOERROR) {
            msg = "ADC configuration failed";
            return std::make_pair(FALSE, msg);
    }

    if ((status = olDaConfig(board.hdass)) != OLNOERROR) {
        msg = "Failed to apply configuration";
    }

    return std::make_pair(TRUE, msg);
}

std::pair<BOOL, std::string> initBoard(DBL freq = 20000., UINT buffer_len = 1024) {
    std::string msg = "";

    std::pair configure_result = configureADC(freq);
    if (!configure_result.first) {
        return configure_result;
    }

    // allocate memory for list of buffer pointers
    buffers = (HBUF*)calloc(NUM_BUFFERS, sizeof(HBUF));
    if (!buffers) {

        msg = "buffer alloc failed";
        return std::make_pair(FALSE, msg);
    }

    // allocate memory for each buffer in our list
    for (int i = 0; i < NUM_BUFFERS; i++) {
        if (olDmCallocBuffer(0, 0, buffer_len * NUM_CHANNELS, 2, &buffers[i]) != OLNOERROR) {
            msg = "buffer setup failed";
            return std::make_pair(FALSE, msg);
        }
        if (olDaPutBuffer(board.hdass, buffers[i]) != OLNOERROR) {
            msg = "buffer queue failed";
            return std::make_pair(FALSE, msg);
        }
    }

    return std::make_pair(TRUE, msg);
}

ULONGLONG startAcquisition() {

    FILETIME start_time;
    GetSystemTimePreciseAsFileTime(&start_time);

    if (olDaStart(board.hdass) != OLNOERROR) {
        return -1;
    }

    ULONGLONG start_time_100ns = ((ULONGLONG)start_time.dwHighDateTime << 32) | start_time.dwLowDateTime;
    ULONGLONG start_time_ns = (start_time_100ns - EPOCH_DIFF_100NS) * 100; // start time in DC2 format

    return start_time_ns;
}

DBL ConvertToDBL(WORD rawValue, UINT resolution, UINT encoding, DBL max, DBL min) {

    if (encoding != OL_ENC_BINARY) {
        // Convert from two's complement to straight binary
        rawValue ^= 1L << (resolution-1);
    }
    
    return ((DBL)rawValue * (max - min)) / (1L << resolution) + min;
}

std::vector<std::vector<DBL>> processAcquisition() {
    HBUF hBuffer;
    std::vector<std::vector<DBL>> buffer;
    
    if (olDaGetBuffer(board.hdass, &hBuffer) == OLNOERROR && hBuffer) { // remove oldest buffer from the queue (we still can't directly access the buffer)
        PWORD samples;
        ULNG  validSamples;

        if (olDmGetBufferPtr(hBuffer, (LPVOID*)&samples) == OLNOERROR && // get a buffer for us to manipulate
            olDmGetValidSamples(hBuffer, &validSamples) == OLNOERROR) { // get the number of samples in our buffer that are real data (i.e., if collection stops mid-buffer, where does data end)

                // init output buffer
                buffer.resize(2);
                buffer[0].resize(validSamples / 2); // voltage
                buffer[1].resize(validSamples / 2); //current

                for (ULNG i = 0; i < validSamples; i += NUM_CHANNELS) {
                    WORD voltageRaw = samples[i];
                    WORD currentRaw = samples[i + 1];
                    
                    buffer[0][i / 2] = ConvertToDBL(voltageRaw, 16, OL_ENC_BINARY, 10., -10.) * 10.; // apply voltage scaling
                    buffer[1][i / 2] = ConvertToDBL(currentRaw, 16, OL_ENC_BINARY, 10., -10.) * 100.; // apply current scaling
                }
            }

        olDaPutBuffer(board.hdass, hBuffer);

    }

    return buffer;
}

BOOL stopCollection() {
    olDaStop(board.hdass);
    olDaFlushBuffers(board.hdass);

    return TRUE;
}

VOID deleteBoard() {

    olDaTerminate(board.hdrvr);

    if (buffers) {
        for (int i = 0; i < NUM_BUFFERS; i++) {
            if (buffers[i]) {
                olDmFreeBuffer(buffers[i]);
            }
        }

        free(buffers);
    }

    if (board.hdass) {
        olDaReleaseDASS(board.hdass);
    }
}


NB_MODULE(lembox_bindings, m) {
    m.def("detectBoard", &detectBoard);
    m.def("deleteBoard", &deleteBoard);
    m.def("initBoard"  , &initBoard, "freq"_a = 20000., "buffer_len"_a = 1024);
    m.def("startCollection", &startAcquisition);
    m.def("sampleBuffer", &processAcquisition);
    m.def("stopCollection", &stopCollection);
}
