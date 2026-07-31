// SPDX-License-Identifier: GPL-3.0-or-later
// Independent DXGI/D3D9 ETW frame timing collector for MCNeteaseToolPE.

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <evntrace.h>
#include <evntcons.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>

namespace {

constexpr GUID kDxgiProvider = {
    0xCA11C036, 0x0102, 0x4A2D, {0xA6, 0xAD, 0xF0, 0x3C, 0xFE, 0xD5, 0xD3, 0xC9}
};
constexpr GUID kD3d9Provider = {
    0x783ACA0A, 0x790E, 0x4D7F, {0x84, 0x51, 0xAA, 0x85, 0x05, 0x11, 0xC6, 0xB9}
};
constexpr USHORT kDxgiPresentStart = 0x002A;
constexpr USHORT kDxgiPresentStop = 0x002B;
constexpr USHORT kD3d9PresentStart = 0x0001;
constexpr USHORT kD3d9PresentStop = 0x0002;
constexpr ULONG kDefaultCapacity = 120000;
constexpr size_t kSessionNameLength = 128;

struct FrameSample {
    uint64_t sequence = 0;
    double timestamp_seconds = 0.0;
    double interval_ms = 0.0;
    double present_call_ms = 0.0;
};

struct PendingPresent {
    LONGLONG started_at = 0;
    uint64_t sequence = 0;
};

struct TraceProperties {
    EVENT_TRACE_PROPERTIES properties{};
    WCHAR session_name[kSessionNameLength]{};
};

std::mutex g_mutex;
std::deque<FrameSample> g_samples;
std::unordered_map<ULONG, PendingPresent> g_pending;
std::atomic<bool> g_running{false};
TRACEHANDLE g_session_handle = 0;
TRACEHANDLE g_trace_handle = INVALID_PROCESSTRACE_HANDLE;
std::thread g_trace_thread;
ULONG g_target_pid = 0;
ULONG g_capacity = kDefaultCapacity;
LONGLONG g_frequency = 1;
LONGLONG g_first_timestamp = 0;
LONGLONG g_last_present_start = 0;
uint64_t g_next_sequence = 1;
std::wstring g_session_name;
TraceProperties g_properties{};

bool IsProvider(const GUID& actual, const GUID& expected) {
    return InlineIsEqualGUID(actual, expected) != FALSE;
}

void RecordStart(const EVENT_RECORD& event) {
    const auto timestamp = event.EventHeader.TimeStamp.QuadPart;
    const auto thread_id = event.EventHeader.ThreadId;
    std::lock_guard<std::mutex> guard(g_mutex);
    if (g_first_timestamp == 0) {
        g_first_timestamp = timestamp;
    }
    FrameSample sample{};
    sample.sequence = g_next_sequence++;
    sample.timestamp_seconds = static_cast<double>(timestamp - g_first_timestamp) /
        static_cast<double>(g_frequency);
    if (g_last_present_start != 0 && timestamp > g_last_present_start) {
        sample.interval_ms = static_cast<double>(timestamp - g_last_present_start) * 1000.0 /
            static_cast<double>(g_frequency);
    }
    g_last_present_start = timestamp;
    g_pending[thread_id] = PendingPresent{timestamp, sample.sequence};
    g_samples.push_back(sample);
    while (g_samples.size() > g_capacity) {
        g_samples.pop_front();
    }
}

void RecordStop(const EVENT_RECORD& event) {
    const auto timestamp = event.EventHeader.TimeStamp.QuadPart;
    const auto thread_id = event.EventHeader.ThreadId;
    std::lock_guard<std::mutex> guard(g_mutex);
    const auto pending = g_pending.find(thread_id);
    if (pending == g_pending.end()) {
        return;
    }
    const auto sequence = pending->second.sequence;
    const auto started_at = pending->second.started_at;
    g_pending.erase(pending);
    const auto sample = std::find_if(
        g_samples.rbegin(),
        g_samples.rend(),
        [sequence](const FrameSample& item) { return item.sequence == sequence; });
    if (sample != g_samples.rend() && timestamp >= started_at) {
        sample->present_call_ms = static_cast<double>(timestamp - started_at) * 1000.0 /
            static_cast<double>(g_frequency);
    }
}

void WINAPI EventRecordCallback(PEVENT_RECORD event) {
    if (event == nullptr || event->EventHeader.ProcessId != g_target_pid) {
        return;
    }
    const auto& provider = event->EventHeader.ProviderId;
    const auto event_id = event->EventHeader.EventDescriptor.Id;
    const bool is_dxgi = IsProvider(provider, kDxgiProvider);
    const bool is_d3d9 = IsProvider(provider, kD3d9Provider);
    if ((is_dxgi && event_id == kDxgiPresentStart) ||
        (is_d3d9 && event_id == kD3d9PresentStart)) {
        RecordStart(*event);
    } else if ((is_dxgi && event_id == kDxgiPresentStop) ||
               (is_d3d9 && event_id == kD3d9PresentStop)) {
        RecordStop(*event);
    }
}

ULONG EnableProvider(const GUID& provider) {
    return EnableTraceEx2(
        g_session_handle,
        &provider,
        EVENT_CONTROL_CODE_ENABLE_PROVIDER,
        TRACE_LEVEL_VERBOSE,
        ~0ULL,
        0,
        0,
        nullptr);
}

void ResetData() {
    std::lock_guard<std::mutex> guard(g_mutex);
    g_samples.clear();
    g_pending.clear();
    g_first_timestamp = 0;
    g_last_present_start = 0;
    g_next_sequence = 1;
}

void ResetHandles() {
    g_session_handle = 0;
    g_trace_handle = INVALID_PROCESSTRACE_HANDLE;
    g_target_pid = 0;
    g_session_name.clear();
}

}  // namespace

extern "C" __declspec(dllexport) ULONG StartNativeFrameCapture(ULONG target_pid, ULONG capacity) {
    if (target_pid == 0) {
        return ERROR_INVALID_PARAMETER;
    }
    if (g_running.exchange(true)) {
        return ERROR_BUSY;
    }
    g_target_pid = target_pid;
    g_capacity = capacity == 0 ? kDefaultCapacity : capacity;
    LARGE_INTEGER frequency{};
    if (!QueryPerformanceFrequency(&frequency)) {
        g_running = false;
        return GetLastError();
    }
    g_frequency = frequency.QuadPart;
    ResetData();

    g_session_name = L"MCNeteaseToolPE.NativeFrames." + std::to_wstring(GetCurrentProcessId()) +
        L"." + std::to_wstring(target_pid);
    ZeroMemory(&g_properties, sizeof(g_properties));
    g_properties.properties.Wnode.BufferSize = sizeof(g_properties);
    g_properties.properties.Wnode.Flags = WNODE_FLAG_TRACED_GUID;
    g_properties.properties.Wnode.ClientContext = 1;
    g_properties.properties.BufferSize = 64;
    g_properties.properties.MinimumBuffers = 4;
    g_properties.properties.MaximumBuffers = 64;
    g_properties.properties.FlushTimer = 1;
    g_properties.properties.LogFileMode = EVENT_TRACE_REAL_TIME_MODE;
    g_properties.properties.LoggerNameOffset = offsetof(TraceProperties, session_name);

    ULONG status = StartTraceW(&g_session_handle, g_session_name.c_str(), &g_properties.properties);
    if (status != ERROR_SUCCESS) {
        g_running = false;
        ResetHandles();
        return status;
    }
    status = EnableProvider(kDxgiProvider);
    if (status == ERROR_SUCCESS) {
        status = EnableProvider(kD3d9Provider);
    }
    if (status != ERROR_SUCCESS) {
        ControlTraceW(g_session_handle, g_session_name.c_str(), &g_properties.properties, EVENT_TRACE_CONTROL_STOP);
        g_running = false;
        ResetHandles();
        return status;
    }

    EVENT_TRACE_LOGFILEW logfile{};
    logfile.LoggerName = const_cast<LPWSTR>(g_session_name.c_str());
    logfile.ProcessTraceMode = PROCESS_TRACE_MODE_REAL_TIME |
        PROCESS_TRACE_MODE_EVENT_RECORD |
        PROCESS_TRACE_MODE_RAW_TIMESTAMP;
    logfile.EventRecordCallback = EventRecordCallback;
    g_trace_handle = OpenTraceW(&logfile);
    if (g_trace_handle == INVALID_PROCESSTRACE_HANDLE) {
        status = GetLastError();
        ControlTraceW(g_session_handle, g_session_name.c_str(), &g_properties.properties, EVENT_TRACE_CONTROL_STOP);
        g_running = false;
        ResetHandles();
        return status;
    }
    g_trace_thread = std::thread([]() {
        TRACEHANDLE handle = g_trace_handle;
        ProcessTrace(&handle, 1, nullptr, nullptr);
    });
    return ERROR_SUCCESS;
}

extern "C" __declspec(dllexport) ULONG StopNativeFrameCapture() {
    if (!g_running.exchange(false)) {
        return ERROR_SUCCESS;
    }
    ULONG status = ControlTraceW(
        g_session_handle,
        g_session_name.c_str(),
        &g_properties.properties,
        EVENT_TRACE_CONTROL_STOP);
    if (g_trace_handle != INVALID_PROCESSTRACE_HANDLE) {
        CloseTrace(g_trace_handle);
    }
    if (g_trace_thread.joinable()) {
        g_trace_thread.join();
    }
    ResetHandles();
    return status == ERROR_WMI_INSTANCE_NOT_FOUND ? ERROR_SUCCESS : status;
}

extern "C" __declspec(dllexport) ULONG GetNativeFrameCount(ULONG* count) {
    if (count == nullptr) {
        return ERROR_INVALID_PARAMETER;
    }
    std::lock_guard<std::mutex> guard(g_mutex);
    *count = static_cast<ULONG>(g_samples.size());
    return ERROR_SUCCESS;
}

extern "C" __declspec(dllexport) ULONG GetNativeFrameData(
    ULONG capacity,
    double* timestamps,
    double* intervals_ms,
    double* present_call_ms,
    ULONG* returned) {
    if (capacity == 0 || timestamps == nullptr || intervals_ms == nullptr ||
        present_call_ms == nullptr || returned == nullptr) {
        return ERROR_INVALID_PARAMETER;
    }
    std::lock_guard<std::mutex> guard(g_mutex);
    const auto count = std::min<size_t>(capacity, g_samples.size());
    const auto start = g_samples.size() - count;
    for (size_t index = 0; index < count; ++index) {
        const auto& sample = g_samples[start + index];
        timestamps[index] = sample.timestamp_seconds;
        intervals_ms[index] = sample.interval_ms;
        present_call_ms[index] = sample.present_call_ms;
    }
    *returned = static_cast<ULONG>(count);
    return ERROR_SUCCESS;
}
