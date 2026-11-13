#include "wifi_board.h"
#include "codecs/es8311_audio_codec.h"
#include "display/lcd_display.h"
#include "application.h"
#include "button.h"
#include "config.h"
#include "i2c_device.h"
#include "assets/lang_config.h"

#include <esp_log.h>
#include <driver/i2c_master.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_lcd_gc9a01.h>
#include <esp_lcd_panel_st7789.h>
#include "display/lvgl_display/lvgl_image.h"
#include "assets.h"
#include <cstring>
#include <memory>
#include <vector>
#include <cmath>
#include <cstdio>

#define TAG "AtomS3R+EchoBase"

// v1 像素 UI：整屏居中显示状态表情 + 底部小状态图标；不改语音链
enum class PixelUiState { Idle, Listening, Thinking, Speaking };

class PixelUiDisplay : public SpiLcdDisplay {
public:
    PixelUiDisplay(esp_lcd_panel_io_handle_t io, esp_lcd_panel_handle_t panel,
                   int w, int h, int ox, int oy, bool mx, bool my, bool swap)
        : SpiLcdDisplay(io, panel, w, h, ox, oy, mx, my, swap) {}

    void SetupUI() override {
        if (IsSetupUICalled()) return;
        SpiLcdDisplay::SetupUI();
        DisplayLockGuard lock(this);
        lv_obj_t* screen = lv_screen_active();
        lv_obj_set_style_bg_color(screen, lv_color_black(), 0);
        if (top_bar_) lv_obj_add_flag(top_bar_, LV_OBJ_FLAG_HIDDEN);
        if (status_bar_) lv_obj_add_flag(status_bar_, LV_OBJ_FLAG_HIDDEN);
        if (content_) lv_obj_add_flag(content_, LV_OBJ_FLAG_HIDDEN);
        if (emoji_label_) lv_obj_add_flag(emoji_label_, LV_OBJ_FLAG_HIDDEN);
        if (emoji_box_) lv_obj_add_flag(emoji_box_, LV_OBJ_FLAG_HIDDEN);
        if (emoji_image_) lv_obj_add_flag(emoji_image_, LV_OBJ_FLAG_HIDDEN);
        if (preview_image_) lv_obj_add_flag(preview_image_, LV_OBJ_FLAG_HIDDEN);
        ui_img_ = lv_image_create(screen);
        lv_obj_set_size(ui_img_, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        lv_obj_align(ui_img_, LV_ALIGN_CENTER, 0, -14);
        lv_image_set_scale(ui_img_, 256); // 帧原生 88px，1:1
        lv_obj_remove_flag(ui_img_, LV_OBJ_FLAG_HIDDEN);
        BuildStatusIcons(screen);
        LoadFrames();
        SwitchState(PixelUiState::Idle);
        timer_ = lv_timer_create(&PixelUiDisplay::TimerCb, 80, this); // 12.5fps
    }

    void SetStatus(const char* status) override {
        if (!IsSetupUICalled() || status == nullptr) return;
        DisplayLockGuard lock(this);
        if (strcmp(status, Lang::Strings::STANDBY) == 0) SwitchState(PixelUiState::Idle);
        else if (strcmp(status, Lang::Strings::LISTENING) == 0) SwitchState(PixelUiState::Listening);
        else if (strcmp(status, Lang::Strings::SPEAKING) == 0) SwitchState(PixelUiState::Speaking);
        else if (strcmp(status, Lang::Strings::CONNECTING) == 0) SwitchState(PixelUiState::Thinking);
    }
    void SetEmotion(const char* emotion) override { (void)emotion; }
    void SetChatMessage(const char* role, const char* content) override { (void)role; (void)content; }
    void ShowNotification(const char* n, int d = 3000) override { (void)n; (void)d; }
    void UpdateStatusBar(bool update_all = false) override { (void)update_all; }

private:
    std::vector<std::unique_ptr<LvglRawImage>> idle_frames_, listen_, think_, speak_;
    lv_timer_t* timer_ = nullptr;
    lv_obj_t* ui_img_ = nullptr;
    PixelUiState state_ = PixelUiState::Idle;
    uint32_t tick_ = 0;
    int frame_ = 0;
    bool load_tried_ = false;
    lv_obj_t* ring_ = nullptr;
    lv_obj_t* dots_[3] = {nullptr, nullptr, nullptr};
    lv_obj_t* bars_[3] = {nullptr, nullptr, nullptr};

    lv_obj_t* MakeDot(lv_obj_t* parent, int x, int y, int sz, uint32_t color) {
        lv_obj_t* o = lv_obj_create(parent);
        lv_obj_set_size(o, sz, sz);
        lv_obj_set_style_radius(o, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(o, lv_color_hex(color), 0);
        lv_obj_set_style_bg_opa(o, LV_OPA_COVER, 0);
        lv_obj_set_style_border_width(o, 0, 0);
        lv_obj_set_style_pad_all(o, 0, 0);
        lv_obj_align(o, LV_ALIGN_BOTTOM_MID, x, y);
        lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
        return o;
    }

    void BuildStatusIcons(lv_obj_t* parent) {
        ring_ = lv_obj_create(parent);
        lv_obj_set_size(ring_, 18, 18);
        lv_obj_set_style_radius(ring_, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(ring_, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(ring_, 2, 0);
        lv_obj_set_style_border_color(ring_, lv_color_hex(0x1E90FF), 0);
        lv_obj_set_style_pad_all(ring_, 0, 0);
        lv_obj_align(ring_, LV_ALIGN_BOTTOM_MID, 0, -3);
        lv_obj_add_flag(ring_, LV_OBJ_FLAG_HIDDEN);
        for (int i = 0; i < 3; i++) dots_[i] = MakeDot(parent, (i - 1) * 10, -6, 5, 0xE0E0E0);
        const int hs[3] = {6, 12, 8};
        for (int i = 0; i < 3; i++) {
            bars_[i] = lv_obj_create(parent);
            lv_obj_set_size(bars_[i], 4, hs[i]);
            lv_obj_set_style_radius(bars_[i], 1, 0);
            lv_obj_set_style_bg_color(bars_[i], lv_color_hex(0x1E90FF), 0);
            lv_obj_set_style_bg_opa(bars_[i], LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(bars_[i], 0, 0);
            lv_obj_set_style_pad_all(bars_[i], 0, 0);
            lv_obj_align(bars_[i], LV_ALIGN_BOTTOM_MID, (i - 1) * 8, -4);
            lv_obj_add_flag(bars_[i], LV_OBJ_FLAG_HIDDEN);
        }
    }

    static void TimerCb(lv_timer_t* t) {
        auto* self = static_cast<PixelUiDisplay*>(lv_timer_get_user_data(t));
        if (self) self->OnTick();
    }

    void LoadSet(const char* prefix, int n, std::vector<std::unique_ptr<LvglRawImage>>& out) {
        out.clear();
        for (int i = 0; i < n; i++) {
            char name[40];
            snprintf(name, sizeof(name), "%s-%02d.png", prefix, i);
            void* ptr = nullptr; size_t size = 0;
            if (Assets::GetInstance().GetAssetData(name, ptr, size)) {
                out.emplace_back(new LvglRawImage(ptr, size));
            } else {
                ESP_LOGW(TAG, "missing frame %s", name);
            }
        }
        ESP_LOGI(TAG, "loaded %d/%d %s frames", (int)out.size(), n, prefix);
    }

    void LoadFrames() {
        LoadSet("idle", 16, idle_frames_);
        LoadSet("listen", 12, listen_);
        LoadSet("think", 10, think_);
        LoadSet("speak", 10, speak_);
        load_tried_ = !idle_frames_.empty() || !listen_.empty() || !think_.empty() || !speak_.empty();
    }

    void ShowFrame(std::vector<std::unique_ptr<LvglRawImage>>& set, int idx) {
        if (set.empty() || !ui_img_) return;
        if (idx < 0 || idx >= (int)set.size()) idx = 0;
        lv_image_set_src(ui_img_, set[idx]->image_dsc());
        lv_obj_remove_flag(ui_img_, LV_OBJ_FLAG_HIDDEN);
    }

    void SwitchState(PixelUiState s) {
        state_ = s; tick_ = 0; frame_ = 0;
        if (ring_) lv_obj_add_flag(ring_, LV_OBJ_FLAG_HIDDEN);
        for (auto d : dots_) if (d) lv_obj_add_flag(d, LV_OBJ_FLAG_HIDDEN);
        for (auto b : bars_) if (b) lv_obj_add_flag(b, LV_OBJ_FLAG_HIDDEN);
        if (!load_tried_) LoadFrames();
        switch (s) {
            case PixelUiState::Idle:
                ShowFrame(idle_frames_, 0);
                break;
            case PixelUiState::Listening:
                ShowFrame(listen_, 0);
                if (ring_) lv_obj_remove_flag(ring_, LV_OBJ_FLAG_HIDDEN);
                break;
            case PixelUiState::Thinking:
                ShowFrame(think_, 0);
                for (auto d : dots_) if (d) lv_obj_remove_flag(d, LV_OBJ_FLAG_HIDDEN);
                break;
            case PixelUiState::Speaking:
                ShowFrame(speak_, 0);
                for (auto b : bars_) if (b) lv_obj_remove_flag(b, LV_OBJ_FLAG_HIDDEN);
                break;
        }
    }

    void OnTick() {
        if (!ui_img_) return;
        tick_++;
        if (!load_tried_) LoadFrames();
        auto* set = (state_ == PixelUiState::Idle) ? &idle_frames_
                  : (state_ == PixelUiState::Listening) ? &listen_
                  : (state_ == PixelUiState::Thinking) ? &think_ : &speak_;
        if (!set->empty()) {
            frame_ = (frame_ + 1) % (int)set->size();
            lv_image_set_src(ui_img_, (*set)[frame_]->image_dsc());
        }
    }
};

#define PI4IOE_ADDR          0x43
#define PI4IOE_REG_CTRL      0x00
#define PI4IOE_REG_IO_PP     0x07
#define PI4IOE_REG_IO_DIR    0x03
#define PI4IOE_REG_IO_OUT    0x05
#define PI4IOE_REG_IO_PULLUP 0x0D

class Pi4ioe : public I2cDevice {
public:
    Pi4ioe(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr) {
        WriteReg(PI4IOE_REG_IO_PP, 0x00); // Set to high-impedance
        WriteReg(PI4IOE_REG_IO_PULLUP, 0xFF); // Enable pull-up
        WriteReg(PI4IOE_REG_IO_DIR, 0x6E); // Set input=0, output=1
        WriteReg(PI4IOE_REG_IO_OUT, 0xFF); // Set outputs to 1
    }

    void SetSpeakerMute(bool mute) {
        WriteReg(PI4IOE_REG_IO_OUT, mute ? 0x00 : 0xFF);
    }
};

class Lp5562 : public I2cDevice {
public:
    Lp5562(i2c_master_bus_handle_t i2c_bus, uint8_t addr) : I2cDevice(i2c_bus, addr) {
        WriteReg(0x00, 0B01000000); // Set chip_en to 1
        WriteReg(0x08, 0B00000001); // Enable internal clock
        WriteReg(0x70, 0B00000000); // Configure all LED outputs to be controlled from I2C registers

        // PWM clock frequency 558 Hz
        auto data = ReadReg(0x08);
        data = data | 0B01000000;
        WriteReg(0x08, data);
    }

    void SetBrightness(uint8_t brightness) {
        // Map 0~100 to 0~255
        brightness = brightness * 255 / 100;
        WriteReg(0x0E, brightness);
    }
};

class CustomBacklight : public Backlight {
public:
    CustomBacklight(Lp5562* lp5562) : lp5562_(lp5562) {}

    void SetBrightnessImpl(uint8_t brightness) override {
        if (lp5562_) {
            lp5562_->SetBrightness(brightness);
        } else {
            ESP_LOGE(TAG, "LP5562 not available");
        }
    }

private:
    Lp5562* lp5562_ = nullptr;
};

static const gc9a01_lcd_init_cmd_t gc9107_lcd_init_cmds[] = {
    //  {cmd, { data }, data_size, delay_ms}
    {0xfe, (uint8_t[]){0x00}, 0, 0},
    {0xef, (uint8_t[]){0x00}, 0, 0},
    {0xb0, (uint8_t[]){0xc0}, 1, 0},
    {0xb2, (uint8_t[]){0x2f}, 1, 0},
    {0xb3, (uint8_t[]){0x03}, 1, 0},
    {0xb6, (uint8_t[]){0x19}, 1, 0},
    {0xb7, (uint8_t[]){0x01}, 1, 0},
    {0xac, (uint8_t[]){0xcb}, 1, 0},
    {0xab, (uint8_t[]){0x0e}, 1, 0},
    {0xb4, (uint8_t[]){0x04}, 1, 0},
    {0xa8, (uint8_t[]){0x19}, 1, 0},
    {0xb8, (uint8_t[]){0x08}, 1, 0},
    {0xe8, (uint8_t[]){0x24}, 1, 0},
    {0xe9, (uint8_t[]){0x48}, 1, 0},
    {0xea, (uint8_t[]){0x22}, 1, 0},
    {0xc6, (uint8_t[]){0x30}, 1, 0},
    {0xc7, (uint8_t[]){0x18}, 1, 0},
    {0xf0,
    (uint8_t[]){0x1f, 0x28, 0x04, 0x3e, 0x2a, 0x2e, 0x20, 0x00, 0x0c, 0x06,
                0x00, 0x1c, 0x1f, 0x0f},
    14, 0},
    {0xf1,
    (uint8_t[]){0x00, 0x2d, 0x2f, 0x3c, 0x6f, 0x1c, 0x0b, 0x00, 0x00, 0x00,
                0x07, 0x0d, 0x11, 0x0f},
    14, 0},
};

class AtomS3rEchoBaseBoard : public WifiBoard {
private:
    i2c_master_bus_handle_t i2c_bus_;
    i2c_master_bus_handle_t i2c_bus_internal_;
    Pi4ioe* pi4ioe_ = nullptr;
    Lp5562* lp5562_ = nullptr;
    Display* display_ = nullptr;
    Button boot_button_;
    bool is_echo_base_connected_ = false;

    void InitializeI2c() {
        // Initialize I2C peripheral
        i2c_master_bus_config_t i2c_bus_cfg = {
            .i2c_port = I2C_NUM_1,
            .sda_io_num = AUDIO_CODEC_I2C_SDA_PIN,
            .scl_io_num = AUDIO_CODEC_I2C_SCL_PIN,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = {
                .enable_internal_pullup = 1,
            },
        };
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_));
        
        i2c_bus_cfg.i2c_port = I2C_NUM_0;
        i2c_bus_cfg.sda_io_num = GPIO_NUM_45;
        i2c_bus_cfg.scl_io_num = GPIO_NUM_0;
        ESP_ERROR_CHECK(i2c_new_master_bus(&i2c_bus_cfg, &i2c_bus_internal_));
    }

    void I2cDetect() {
        is_echo_base_connected_ = false;
        uint8_t echo_base_connected_flag = 0x00;
        uint8_t address;
        printf("     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f\r\n");
        for (int i = 0; i < 128; i += 16) {
            printf("%02x: ", i);
            for (int j = 0; j < 16; j++) {
                fflush(stdout);
                address = i + j;
                esp_err_t ret = i2c_master_probe(i2c_bus_, address, pdMS_TO_TICKS(200));
                if (ret == ESP_OK) {
                    printf("%02x ", address);
                    if (address == 0x18) {
                        echo_base_connected_flag |= 0xF0;
                    } else if (address == 0x43) {
                        echo_base_connected_flag |= 0x0F;
                    }
                } else if (ret == ESP_ERR_TIMEOUT) {
                    printf("UU ");
                } else {
                    printf("-- ");
                }
            }
            printf("\r\n");
        }
        is_echo_base_connected_ = (echo_base_connected_flag == 0xFF);
    }

    void CheckEchoBaseConnection() {
        if (is_echo_base_connected_) {
            return;
        }
        
        // Pop error page
        InitializeLp5562();
        InitializeSpi();
        InitializeGc9107Display();
        InitializeButtons();
        GetBacklight()->SetBrightness(100);
        
        // Ensure UI is set up before displaying error
        display_->SetupUI();
        
        display_->SetStatus(Lang::Strings::ERROR);
        display_->SetEmotion("triangle_exclamation");
        display_->SetChatMessage("system", "Echo Base\nnot connected");
        
        while (1) {
            ESP_LOGE(TAG, "Atomic Echo Base is disconnected");
            vTaskDelay(pdMS_TO_TICKS(1000));

            // Rerun detection
            I2cDetect();
            if (is_echo_base_connected_) {
                vTaskDelay(pdMS_TO_TICKS(500));
                I2cDetect();
                if (is_echo_base_connected_) {
                    ESP_LOGI(TAG, "Atomic Echo Base is reconnected");
                    vTaskDelay(pdMS_TO_TICKS(200));
                    esp_restart();
                }
            }
        }
    }

    void InitializePi4ioe() {
        ESP_LOGI(TAG, "Init PI4IOE");
        pi4ioe_ = new Pi4ioe(i2c_bus_, PI4IOE_ADDR);
        pi4ioe_->SetSpeakerMute(false);
    }

    void InitializeLp5562() {
        ESP_LOGI(TAG, "Init LP5562");
        lp5562_ = new Lp5562(i2c_bus_internal_, 0x30);
    }

    void InitializeSpi() {
        ESP_LOGI(TAG, "Initialize SPI bus");
        spi_bus_config_t buscfg = {};
        buscfg.mosi_io_num = GPIO_NUM_21;
        buscfg.miso_io_num = GPIO_NUM_NC;
        buscfg.sclk_io_num = GPIO_NUM_15;
        buscfg.quadwp_io_num = GPIO_NUM_NC;
        buscfg.quadhd_io_num = GPIO_NUM_NC;
        buscfg.max_transfer_sz = DISPLAY_WIDTH * DISPLAY_HEIGHT * sizeof(uint16_t);
        ESP_ERROR_CHECK(spi_bus_initialize(SPI3_HOST, &buscfg, SPI_DMA_CH_AUTO));
    }

    void InitializeGc9107Display() {
        ESP_LOGI(TAG, "Init GC9107 display");

        ESP_LOGI(TAG, "Install panel IO");
        esp_lcd_panel_io_handle_t io_handle = NULL;
        esp_lcd_panel_io_spi_config_t io_config = {};
        io_config.cs_gpio_num = GPIO_NUM_14;
        io_config.dc_gpio_num = GPIO_NUM_42;
        io_config.spi_mode = 0;
        io_config.pclk_hz = 40 * 1000 * 1000;
        io_config.trans_queue_depth = 10;
        io_config.lcd_cmd_bits = 8;
        io_config.lcd_param_bits = 8;
        ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(SPI3_HOST, &io_config, &io_handle));
    
        ESP_LOGI(TAG, "Install GC9A01 panel driver");
        esp_lcd_panel_handle_t panel_handle = NULL;
        gc9a01_vendor_config_t gc9107_vendor_config = {
            .init_cmds = gc9107_lcd_init_cmds,
            .init_cmds_size = sizeof(gc9107_lcd_init_cmds) / sizeof(gc9a01_lcd_init_cmd_t),
        };
        esp_lcd_panel_dev_config_t panel_config = {};
        panel_config.reset_gpio_num = GPIO_NUM_48; // Set to -1 if not use
        panel_config.rgb_endian = LCD_RGB_ENDIAN_BGR;
        panel_config.bits_per_pixel = 16; // Implemented by LCD command `3Ah` (16/18)
        panel_config.vendor_config = &gc9107_vendor_config;

        ESP_ERROR_CHECK(esp_lcd_new_panel_st7789(io_handle, &panel_config, &panel_handle));
        ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_handle));
        ESP_ERROR_CHECK(esp_lcd_panel_init(panel_handle));
        // 官方 GC9107(AtomS3R)：132x130 显存，128x128 可视区在 (2,1)；需颜色反相
        ESP_ERROR_CHECK(esp_lcd_panel_invert_color(panel_handle, true));
        ESP_ERROR_CHECK(esp_lcd_panel_set_gap(panel_handle, 2, 1));
        ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_handle, true)); 

        display_ = new PixelUiDisplay(io_handle, panel_handle,
                                    DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_OFFSET_X, DISPLAY_OFFSET_Y, DISPLAY_MIRROR_X, DISPLAY_MIRROR_Y, DISPLAY_SWAP_XY);
    }

    void InitializeButtons() {
        boot_button_.OnClick([this]() {
            auto& app = Application::GetInstance();
            if (app.GetDeviceState() == kDeviceStateStarting) {
                EnterWifiConfigMode();
                return;
            }
            app.ToggleChatState();
        });
    }

public:
    AtomS3rEchoBaseBoard() : boot_button_(BOOT_BUTTON_GPIO) {
        InitializeI2c();
        I2cDetect();
        CheckEchoBaseConnection();
        InitializePi4ioe();
        InitializeLp5562();
        InitializeSpi();
        InitializeGc9107Display();
        InitializeButtons();
        GetBacklight()->RestoreBrightness();
    }

    virtual AudioCodec* GetAudioCodec() override {
        static Es8311AudioCodec audio_codec(
            i2c_bus_,
            I2C_NUM_1,
            AUDIO_INPUT_SAMPLE_RATE,
            AUDIO_OUTPUT_SAMPLE_RATE,
            AUDIO_I2S_GPIO_MCLK,
            AUDIO_I2S_GPIO_BCLK,
            AUDIO_I2S_GPIO_WS,
            AUDIO_I2S_GPIO_DOUT,
            AUDIO_I2S_GPIO_DIN,
            AUDIO_CODEC_GPIO_PA,
            AUDIO_CODEC_ES8311_ADDR,
            AUDIO_INPUT_REFERENCE,
            false);  // Echo Base 无独立 MCLK，ES8311 从 BCLK 派生内部时钟（与 M5Unified 一致）
        return &audio_codec;
    }

    virtual Display* GetDisplay() override {
        return display_;
    }

    virtual Backlight *GetBacklight() override {
        static CustomBacklight backlight(lp5562_);
        return &backlight;
    }
};

DECLARE_BOARD(AtomS3rEchoBaseBoard);
