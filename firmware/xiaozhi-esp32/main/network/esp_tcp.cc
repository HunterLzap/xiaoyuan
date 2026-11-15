#include "esp_tcp.h"
#include <esp_log.h>
#include <esp_timer.h>
#include <esp_heap_caps.h>
#include <lwip/tcpip.h>
#include <lwip/priv/tcp_priv.h>
#include <unistd.h>
#include <algorithm>
#include <cstring>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/tcp.h>
#include <netdb.h>
#include <errno.h>

static const char* TAG = "EspTcp";
static constexpr EventBits_t RECEIVE_TASK_EXIT = BIT0;
static constexpr int64_t REALTIME_SEND_DEADLINE_US = 250000;
static constexpr int64_t REALTIME_WRITE_RECHECK_US = 20000;

struct TcpSendSnapshot {
    uint16_t local_port = 0;
    bool found = false;
    int query_error = 0;
    unsigned available_bytes = 0;
    unsigned queued_buffers = 0;
    unsigned unsent_segments = 0;
    unsigned unacked_segments = 0;
    uint32_t acknowledged = 0;
    uint32_t peer_window = 0;
    uint32_t congestion_window = 0;
    unsigned retransmissions = 0;
    unsigned duplicate_acks = 0;
    int retransmit_age_ms = 0;
    int retransmit_timeout_ms = 0;
};

static TcpSendSnapshot ReadTcpSendSnapshot(int descriptor) {
    TcpSendSnapshot snapshot;
    sockaddr_in local = {};
    socklen_t local_size = sizeof(local);
    if (getsockname(descriptor, reinterpret_cast<sockaddr*>(&local), &local_size) != 0) {
        snapshot.query_error = errno;
        return snapshot;
    }
    snapshot.local_port = ntohs(local.sin_port);
    snapshot.query_error = tcpip_callback_wait([](void* context) {
        auto& state = *static_cast<TcpSendSnapshot*>(context);
        for (auto* pcb = tcp_active_pcbs; pcb != nullptr; pcb = pcb->next) {
            if (pcb->local_port != state.local_port) {
                continue;
            }
            state.found = true;
            state.available_bytes = tcp_sndbuf(pcb);
            state.queued_buffers = tcp_sndqueuelen(pcb);
            state.acknowledged = pcb->lastack;
            state.peer_window = pcb->snd_wnd;
            state.congestion_window = pcb->cwnd;
            state.retransmissions = pcb->nrtx;
            state.duplicate_acks = pcb->dupacks;
            state.retransmit_age_ms = pcb->rtime * TCP_SLOW_INTERVAL;
            state.retransmit_timeout_ms = pcb->rto * TCP_SLOW_INTERVAL;
            for (auto* segment = pcb->unsent; segment != nullptr; segment = segment->next) {
                ++state.unsent_segments;
            }
            for (auto* segment = pcb->unacked; segment != nullptr; segment = segment->next) {
                ++state.unacked_segments;
            }
            break;
        }
    }, &snapshot);
    return snapshot;
}

EspTcp::EspTcp(bool realtime) : realtime_(realtime) {
    event_group_ = xEventGroupCreate();
}

EspTcp::~EspTcp() {
    Disconnect();
    vEventGroupDelete(event_group_);
}

bool EspTcp::Connect(const std::string& host, int port) {
    Disconnect();
    auto* server = gethostbyname(host.c_str());
    if (!server) {
        last_error_ = h_errno;
        ESP_LOGE(TAG, "TCP resolve failed code=%d", last_error_);
        return false;
    }
    sockaddr_in address = {};
    address.sin_family = AF_INET;
    address.sin_port = htons(port);
    memcpy(&address.sin_addr, server->h_addr, server->h_length);
    tcp_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (tcp_fd_ < 0) {
        last_error_ = errno;
        return false;
    }
    if (connect(tcp_fd_, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0) {
        last_error_ = errno;
        close(tcp_fd_);
        tcp_fd_ = -1;
        ESP_LOGE(TAG, "TCP connect failed errno=%d", last_error_);
        return false;
    }
    if (realtime_) {
        int no_delay = 1;
        timeval receive_timeout = {1, 0};
        if (setsockopt(tcp_fd_, IPPROTO_TCP, TCP_NODELAY, &no_delay, sizeof(no_delay)) != 0 ||
            setsockopt(tcp_fd_, SOL_SOCKET, SO_RCVTIMEO, &receive_timeout, sizeof(receive_timeout)) != 0) {
            last_error_ = errno;
            close(tcp_fd_);
            tcp_fd_ = -1;
            ESP_LOGE(TAG, "TCP realtime socket setup failed errno=%d", last_error_);
            return false;
        }
    }
    connected_ = true;
    xEventGroupClearBits(event_group_, RECEIVE_TASK_EXIT);
    auto created = xTaskCreate([](void* context) {
        auto* tcp = static_cast<EspTcp*>(context);
        tcp->ReceiveTask();
        xEventGroupSetBits(tcp->event_group_, RECEIVE_TASK_EXIT);
        vTaskDelete(nullptr);
    }, "tcp_receive", 4096, this, 1, &receive_task_handle_);
    ESP_ERROR_CHECK(created == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
    return true;
}

void EspTcp::Disconnect() {
    if (connected_) {
        ESP_LOGI(TAG, "TCP local close");
    }
    DoDisconnect(true);
}

void EspTcp::DoDisconnect(bool wait_for_task) {
    bool notify = connected_;
    connected_ = false;
    int descriptor = tcp_fd_;
    tcp_fd_ = -1;
    if (descriptor >= 0) {
        shutdown(descriptor, SHUT_RDWR);
        close(descriptor);
    }
    if (wait_for_task && receive_task_handle_ && xTaskGetCurrentTaskHandle() != receive_task_handle_) {
        auto bits = xEventGroupWaitBits(event_group_, RECEIVE_TASK_EXIT, pdFALSE, pdFALSE, pdMS_TO_TICKS(10000));
        if (!(bits & RECEIVE_TASK_EXIT)) {
            ESP_LOGE(TAG, "TCP receive task did not exit");
        }
    }
    if (notify && disconnect_callback_) {
        disconnect_callback_();
    }
}

int EspTcp::Send(const std::string& data) {
    if (!connected_) {
        return -1;
    }
    int descriptor = tcp_fd_;
    size_t total_sent = 0;
    auto started = esp_timer_get_time();
    unsigned send_calls = 0;
    unsigned would_block_count = 0;
    unsigned select_timeouts = 0;
    int first_send_error = 0;
    int64_t max_send_call_us = 0;
    int64_t select_wait_us = 0;
    TcpSendSnapshot blocked_state;
    while (total_sent < data.size() && connected_) {
        int ret = -1;
        int error = ETIMEDOUT;
        if (!realtime_ || esp_timer_get_time() - started < REALTIME_SEND_DEADLINE_US) {
            auto call_started = esp_timer_get_time();
            ++send_calls;
            ret = send(descriptor, data.data() + total_sent, data.size() - total_sent,
                       realtime_ ? MSG_DONTWAIT : 0);
            error = ret < 0 ? errno : ECONNRESET;
            if (ret < 0 && first_send_error == 0) {
                first_send_error = error;
            }
            max_send_call_us = std::max(max_send_call_us, esp_timer_get_time() - call_started);
        }
        if (ret > 0) {
            total_sent += ret;
            continue;
        }
        if (realtime_ && (error == EAGAIN || error == EWOULDBLOCK)) {
            ++would_block_count;
            if (would_block_count == 1) {
                blocked_state = ReadTcpSendSnapshot(descriptor);
            }
            auto remaining = REALTIME_SEND_DEADLINE_US - (esp_timer_get_time() - started);
            if (remaining > 0) {
                auto wait_us = std::min(remaining, REALTIME_WRITE_RECHECK_US);
                fd_set writable;
                FD_ZERO(&writable);
                FD_SET(descriptor, &writable);
                timeval timeout = {static_cast<long>(wait_us / 1000000),
                                   static_cast<long>(wait_us % 1000000)};
                auto wait_started = esp_timer_get_time();
                int ready = select(descriptor + 1, nullptr, &writable, nullptr, &timeout);
                int select_error = ready < 0 ? errno : 0;
                select_wait_us += esp_timer_get_time() - wait_started;
                if (ready >= 0) {
                    if (ready == 0) {
                        ++select_timeouts;
                    }
                    continue;
                }
                error = select_error;
            } else {
                error = ETIMEDOUT;
            }
        }
        last_error_ = error;
        ESP_LOGE(TAG, "TCP send failed errno=%d sent=%u total=%u duration_ms=%ld "
                 "first_send_errno=%d send_calls=%u would_block=%u select_timeouts=%u "
                 "send_call_max_us=%ld select_ms=%ld",
                 error, static_cast<unsigned>(total_sent), static_cast<unsigned>(data.size()),
                 static_cast<long>((esp_timer_get_time() - started) / 1000),
                 first_send_error, send_calls, would_block_count, select_timeouts,
                 static_cast<long>(max_send_call_us), static_cast<long>(select_wait_us / 1000));
        if (realtime_) {
            if (would_block_count > 0) {
                auto failed_state = ReadTcpSendSnapshot(descriptor);
                bool same_connection = blocked_state.found && failed_state.found
                    && blocked_state.local_port == failed_state.local_port;
                ESP_LOGE(TAG, "TCP backpressure port=%u found=%d/%d query_error=%d/%d "
                         "sndbuf=%u/%u pbufs=%u/%u pbuf_limit=%u unsent=%u/%u unacked=%u/%u "
                         "ack_progress_valid=%d ack_progress=%lu peer_wnd=%lu/%lu cwnd=%lu/%lu",
                         blocked_state.local_port, blocked_state.found, failed_state.found,
                         blocked_state.query_error, failed_state.query_error,
                         blocked_state.available_bytes, failed_state.available_bytes,
                         blocked_state.queued_buffers, failed_state.queued_buffers,
                         static_cast<unsigned>(TCP_SND_QUEUELEN),
                         blocked_state.unsent_segments, failed_state.unsent_segments,
                         blocked_state.unacked_segments, failed_state.unacked_segments,
                         same_connection,
                         static_cast<unsigned long>(same_connection
                             ? failed_state.acknowledged - blocked_state.acknowledged : 0),
                         static_cast<unsigned long>(blocked_state.peer_window),
                         static_cast<unsigned long>(failed_state.peer_window),
                         static_cast<unsigned long>(blocked_state.congestion_window),
                         static_cast<unsigned long>(failed_state.congestion_window));
                ESP_LOGE(TAG, "TCP backpressure retransmits=%u/%u dupacks=%u/%u "
                         "rto_ms=%d/%d retransmit_age_ms=%d/%d "
                         "internal_free=%u internal_largest=%u dma_free=%u dma_largest=%u "
                         "psram_free=%u psram_largest=%u",
                         blocked_state.retransmissions, failed_state.retransmissions,
                         blocked_state.duplicate_acks, failed_state.duplicate_acks,
                         blocked_state.retransmit_timeout_ms, failed_state.retransmit_timeout_ms,
                         blocked_state.retransmit_age_ms, failed_state.retransmit_age_ms,
                         static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
                         static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT)),
                         static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_DMA | MALLOC_CAP_8BIT)),
                         static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_DMA | MALLOC_CAP_8BIT)),
                         static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)),
                         static_cast<unsigned>(heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
            }
            DoDisconnect(false);
        }
        return -1;
    }
    if (total_sent == data.size() && select_timeouts > 0) {
        ESP_LOGI(TAG, "TCP write resumed after select timeout sent=%u duration_ms=%ld "
                 "first_send_errno=%d send_calls=%u select_timeouts=%u",
                 static_cast<unsigned>(total_sent),
                 static_cast<long>((esp_timer_get_time() - started) / 1000),
                 first_send_error, send_calls, select_timeouts);
    }
    return total_sent == data.size() ? static_cast<int>(total_sent) : -1;
}

void EspTcp::ReceiveTask() {
    std::string data;
    while (connected_) {
        data.resize(1500);
        int ret = recv(tcp_fd_, data.data(), data.size(), 0);
        if (ret <= 0) {
            int error = ret < 0 ? errno : 0;
            if (!connected_) {
                break;
            }
            if (ret < 0 && (error == EAGAIN || error == EWOULDBLOCK || error == EINTR)) {
                continue;
            }
            last_error_ = error;
            if (ret < 0) {
                ESP_LOGE(TAG, "TCP receive failed: %d errno=%d", ret, error);
            } else {
                ESP_LOGI(TAG, "TCP peer closed");
            }
            DoDisconnect(false);
            break;
        }
        if (stream_callback_) {
            data.resize(ret);
            stream_callback_(data);
        }
    }
}

int EspTcp::GetLastError() {
    return last_error_;
}
