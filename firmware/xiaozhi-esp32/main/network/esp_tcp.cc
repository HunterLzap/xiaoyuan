#include "esp_tcp.h"
#include <esp_log.h>
#include <esp_timer.h>
#include <unistd.h>
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
    while (total_sent < data.size() && connected_) {
        int ret;
        if (realtime_ && esp_timer_get_time() - started >= REALTIME_SEND_DEADLINE_US) {
            ret = -1;
            errno = ETIMEDOUT;
        } else {
            ret = send(descriptor, data.data() + total_sent, data.size() - total_sent,
                       realtime_ ? MSG_DONTWAIT : 0);
        }
        if (ret > 0) {
            total_sent += ret;
            continue;
        }
        int error = ret < 0 ? errno : ECONNRESET;
        if (realtime_ && (error == EAGAIN || error == EWOULDBLOCK)) {
            auto remaining = REALTIME_SEND_DEADLINE_US - (esp_timer_get_time() - started);
            if (remaining > 0) {
                fd_set writable;
                FD_ZERO(&writable);
                FD_SET(descriptor, &writable);
                timeval timeout = {static_cast<long>(remaining / 1000000),
                                   static_cast<long>(remaining % 1000000)};
                int ready = select(descriptor + 1, nullptr, &writable, nullptr, &timeout);
                if (ready > 0) {
                    continue;
                }
                error = ready == 0 ? ETIMEDOUT : errno;
            } else {
                error = ETIMEDOUT;
            }
        }
        last_error_ = error;
        ESP_LOGE(TAG, "TCP send failed errno=%d sent=%u total=%u duration_ms=%ld",
                 error, static_cast<unsigned>(total_sent), static_cast<unsigned>(data.size()),
                 static_cast<long>((esp_timer_get_time() - started) / 1000));
        if (realtime_) {
            DoDisconnect(false);
        }
        return -1;
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
