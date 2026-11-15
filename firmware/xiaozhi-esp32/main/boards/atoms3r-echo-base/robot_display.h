#pragma once

#include "display/lcd_display.h"
#include "assets/lang_config.h"
#include "assets.h"
#include "device_animation_manifest.h"
#include <wifi_manager.h>
#include <array>
#include <cstring>
#include <ctime>

class RobotDisplay : public SpiLcdDisplay {
public:
    using SpiLcdDisplay::SpiLcdDisplay;

    void SetupUI() override {
        if (IsSetupUICalled()) return;
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);
        auto* screen = lv_screen_active();
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        for (auto* object : {top_bar_, status_bar_, content_, emoji_label_, emoji_box_,
                             emoji_image_, preview_image_, bottom_bar_, side_bar_}) {
            if (object) lv_obj_add_flag(object, LV_OBJ_FLAG_HIDDEN);
        }
        image_ = lv_image_create(screen);
        lv_obj_set_size(image_, 128, 128);
        lv_obj_set_pos(image_, 0, 0);
        clock_label_ = MakeLabel(screen, 0, 18);
        state_label_ = MakeLabel(screen, 106, 22);
        lv_label_set_text(clock_label_, "--:--");
        frames_loaded_ = LoadFrames();
        SwitchAnimation(State::Startup);
        timer_ = lv_timer_create([](lv_timer_t* timer) {
            static_cast<RobotDisplay*>(lv_timer_get_user_data(timer))->OnTick();
        }, DeviceAnimations::kFrameMs, this);
    }

    void SetStatus(const char* status) override {
        if (!IsSetupUICalled() || !status) return;
        DisplayLockGuard lock(this);
        if (strcmp(status, Lang::Strings::STANDBY) == 0) {
            resume_state_ = resting_ ? State::Sleep : State::Idle;
        } else if (strcmp(status, Lang::Strings::LISTENING) == 0) {
            resting_ = false;
            resume_state_ = State::Listening;
            if (state_ == State::Cancel) {
                SetStateLabel(State::Listening);
                return;
            }
        } else if (strcmp(status, Lang::Strings::SPEAKING) == 0) {
            resting_ = false;
            resume_state_ = State::Speaking;
        } else if (strcmp(status, Lang::Strings::CONNECTING) == 0) {
            resting_ = false;
            resume_state_ = State::Connecting;
            if (state_ == State::Wake) {
                SetStateLabel(State::Connecting);
                return;
            }
        } else if (strcmp(status, Lang::Strings::ERROR) == 0) {
            SwitchAnimation(State::Error);
            return;
        } else {
            resume_state_ = State::Connecting;
            SwitchAnimation(resume_state_);
            lv_label_set_text(state_label_, status);
            return;
        }
        SwitchAnimation(network_connected_ ? resume_state_ : State::Disconnected);
    }

    void SetEmotion(const char* emotion) override {
        if (!IsSetupUICalled() || !emotion) return;
        DisplayLockGuard lock(this);
        if (strcmp(emotion, "neutral") == 0) return;
        for (const auto& activity : kActivities) {
            if (strcmp(emotion, activity.name) != 0) continue;
            if (activity.state == State::Sleep) {
                resting_ = true;
                resume_state_ = State::Sleep;
            } else if (activity.state == State::Wake) {
                resting_ = false;
                resume_state_ = State::Connecting;
            } else if (activity.state == State::Cancel || activity.state == State::Clarification
                       || activity.state == State::Listening) {
                resume_state_ = State::Listening;
            } else if (activity.state == State::Success) {
                resume_state_ = State::Thinking;
            } else if (activity.state == State::Thinking || activity.state == State::Searching) {
                resume_state_ = activity.state;
            }
            SwitchAnimation(activity.state);
            return;
        }
    }

    void UpdateStatusBar(bool update_all = false) override {
        if (!IsSetupUICalled()) return;
        bool connected = WifiManager::GetInstance().IsConnected();
        time_t now = time(nullptr);
        struct tm local {};
        localtime_r(&now, &local);
        char text[8] = "--:--";
        if (local.tm_year >= 2025 - 1900) strftime(text, sizeof(text), "%H:%M", &local);
        DisplayLockGuard lock(this);
        if (strcmp(lv_label_get_text(clock_label_), text) != 0) {
            lv_label_set_text(clock_label_, text);
        }
        if (connected != network_connected_) {
            network_connected_ = connected;
            SwitchAnimation(connected ? resume_state_ : State::Disconnected);
        }
    }

    void SetChatMessage(const char* role, const char* content) override {}
    void ShowNotification(const char* notification, int duration_ms = 3000) override {}

private:
    using State = DeviceAnimations::State;
    using Playback = DeviceAnimations::Playback;
    struct Activity { const char* name; State state; };
    inline static constexpr Activity kActivities[] = {
        {"wake", State::Wake}, {"thinking", State::Thinking}, {"searching", State::Searching},
        {"success", State::Success}, {"clarification", State::Clarification},
        {"error", State::Error}, {"triangle_exclamation", State::Error},
        {"sleep", State::Sleep}, {"cancel", State::Cancel}, {"listening", State::Listening}
    };
    std::array<lv_image_dsc_t, std::size(DeviceAnimations::kFrameNames)> frames_ {};
    lv_obj_t* image_ = nullptr;
    lv_obj_t* clock_label_ = nullptr;
    lv_obj_t* state_label_ = nullptr;
    lv_timer_t* timer_ = nullptr;
    State state_ = State::Startup;
    State resume_state_ = State::Idle;
    uint16_t frame_ = 0;
    uint16_t displayed_frame_ = UINT16_MAX;
    uint16_t idle_ticks_ = 0;
    bool network_connected_ = true;
    bool resting_ = false;
    bool frames_loaded_ = false;

    lv_obj_t* MakeLabel(lv_obj_t* parent, int top, int height) {
        auto* label = lv_label_create(parent);
        lv_obj_set_size(label, 128, height);
        lv_obj_set_pos(label, 0, top);
        lv_obj_set_style_text_color(label, lv_color_hex(0xE0E0E0), 0);
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
        int line_height = lv_obj_get_style_text_font(label, LV_PART_MAIN)->line_height;
        lv_obj_set_style_pad_top(label, height > line_height ? (height - line_height) / 2 : 0, 0);
        lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
        return label;
    }

    bool LoadFrames() {
        auto& assets = Assets::GetInstance();
        for (size_t index = 0; index < frames_.size(); ++index) {
            void* data = nullptr;
            size_t size = 0;
            if (!assets.GetAssetData(DeviceAnimations::kFrameNames[index], data, size)
                || size < sizeof(lv_image_header_t)) {
                ESP_LOGE("RobotDisplay", "missing animation asset %s", DeviceAnimations::kFrameNames[index]);
                return false;
            }
            auto& image = frames_[index];
            memcpy(&image.header, data, sizeof(image.header));
            image.data = static_cast<const uint8_t*>(data) + sizeof(image.header);
            image.data_size = size - sizeof(image.header);
        }
        ESP_LOGI("RobotDisplay", "loaded %u unique frames", static_cast<unsigned>(frames_.size()));
        return true;
    }

    void SetStateLabel(State state) {
        lv_label_set_text(state_label_, frames_loaded_
            ? DeviceAnimations::kAnimations[static_cast<size_t>(state)].label : "资源未更新");
    }

    void ShowFrame() {
        if (!frames_loaded_) return;
        const auto& animation = DeviceAnimations::kAnimations[static_cast<size_t>(state_)];
        auto index = animation.frames[frame_];
        if (index == displayed_frame_) return;
        displayed_frame_ = index;
        lv_image_set_src(image_, &frames_[index]);
    }

    void SwitchAnimation(State state) {
        if (state_ == state && displayed_frame_ != UINT16_MAX) return;
        state_ = state;
        frame_ = 0;
        idle_ticks_ = 0;
        SetStateLabel(state);
        ShowFrame();
    }

    void OnTick() {
        const auto& animation = DeviceAnimations::kAnimations[static_cast<size_t>(state_)];
        if (state_ == State::Idle && ++idle_ticks_ == 250) {
            SwitchAnimation(State::IdleAction);
            return;
        }
        if (frame_ + 1 < animation.count) {
            ++frame_;
        } else if (animation.playback == Playback::Loop) {
            frame_ = 0;
        } else if (animation.playback == Playback::Once) {
            SwitchAnimation(state_ == State::Startup || state_ == State::IdleAction
                            ? animation.next : resume_state_);
            return;
        } else {
            return;
        }
        ShowFrame();
    }
};
