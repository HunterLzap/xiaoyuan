#pragma once

#include "tcp.h"
#include <freertos/FreeRTOS.h>
#include <freertos/event_groups.h>
#include <freertos/task.h>

class EspTcp : public Tcp {
public:
    explicit EspTcp(bool realtime = false);
    ~EspTcp();
    bool Connect(const std::string& host, int port) override;
    void Disconnect() override;
    int Send(const std::string& data) override;
    int GetLastError() override;

private:
    int tcp_fd_ = -1;
    EventGroupHandle_t event_group_ = nullptr;
    TaskHandle_t receive_task_handle_ = nullptr;
    int last_error_ = 0;
    bool realtime_ = false;
    void ReceiveTask();
    void DoDisconnect(bool wait_for_task);
};
