#include "es8311_audio_codec.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <esp_log.h>

#define TAG "Es8311AudioCodec"

namespace {
void ComputeMonoStats(const int16_t* samples, int count, long* out_rms, int* out_peak) {
    if (samples == nullptr || count <= 0) {
        *out_rms = 0;
        *out_peak = 0;
        return;
    }
    int64_t sum_sq = 0;
    int peak = 0;
    for (int i = 0; i < count; ++i) {
        int v = samples[i];
        int av = v < 0 ? -v : v;
        if (av > peak) peak = av;
        sum_sq += static_cast<int64_t>(v) * v;
    }
    *out_rms = static_cast<long>(std::sqrt(static_cast<double>(sum_sq) / count));
    *out_peak = peak;
}

void ReadMicWithDiag(esp_codec_dev_handle_t dev, int16_t* dst, int mic_samples, int channels) {
    static uint32_t s_read_diag_count = 0;
    static esp_err_t s_last_ret = ESP_OK;
    esp_err_t read_ret = esp_codec_dev_read(dev, (void*)dst, mic_samples * sizeof(int16_t));
    ESP_ERROR_CHECK_WITHOUT_ABORT(read_ret);
    uint32_t n = ++s_read_diag_count;
    if ((n % 100) == 1 || read_ret != s_last_ret) {
        s_last_ret = read_ret;
        long rms = 0;
        int peak = 0;
        ComputeMonoStats(dst, mic_samples, &rms, &peak);
        ESP_LOGI(TAG, "mic_raw ret=%d samples=%d rms=%ld peak=%d ch=%d",
                 static_cast<int>(read_ret), mic_samples, rms, peak, channels);
    }
}
}  // namespace

// 软件回采起播前置垫零（毫秒）：补偿 Write() 到 I2S TX DMA/DAC/扬声器出声的固定硬件延迟，
// 可按真机录音实测微调（例如 20~60ms）。
#ifndef ES8311_AEC_REF_PREFILL_MS
#define ES8311_AEC_REF_PREFILL_MS 35
#endif

Es8311AudioCodec::Es8311AudioCodec(void* i2c_master_handle, i2c_port_t i2c_port, int input_sample_rate, int output_sample_rate,
    gpio_num_t mclk, gpio_num_t bclk, gpio_num_t ws, gpio_num_t dout, gpio_num_t din,
    gpio_num_t pa_pin, uint8_t es8311_addr, bool input_reference, bool use_mclk, bool pa_inverted) {
    duplex_ = true; // 是否双工
    input_reference_ = input_reference; // 参数化：是否使用参考输入，实现回声消除
    input_channels_ = input_reference_ ? 2 : 1; // 输入通道数（单麦+参考 or 仅单麦）
    input_sample_rate_ = input_sample_rate;
    output_sample_rate_ = output_sample_rate;
    pa_pin_ = pa_pin;
    pa_inverted_ = pa_inverted;
    input_gain_ = 30;

    // 初始化软件回采环形缓冲（至少 500ms @ output_sample_rate_，24kHz 下为 12000 samples）
    if (input_reference_) {
        const size_t cap = std::max<size_t>(8192, static_cast<size_t>(output_sample_rate_ / 2));
        ref_buffer_.assign(cap, 0);
        ref_read_pos_ = 0;
        ref_write_pos_ = 0;
        ref_count_ = 0;
        ref_empty_reads_ = 0;
        ref_primed_ = false;
    }

    assert(input_sample_rate_ == output_sample_rate_);
    CreateDuplexChannels(mclk, bclk, ws, dout, din);

    // Do initialize of related interface: data_if, ctrl_if and gpio_if
    audio_codec_i2s_cfg_t i2s_cfg = {
        .port = I2S_NUM_0,
        .rx_handle = rx_handle_,
        .tx_handle = tx_handle_,
    };
    data_if_ = audio_codec_new_i2s_data(&i2s_cfg);
    assert(data_if_ != NULL);

    // Output
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port = i2c_port,
        .addr = es8311_addr,
        .bus_handle = i2c_master_handle,
    };
    ctrl_if_ = audio_codec_new_i2c_ctrl(&i2c_cfg);
    assert(ctrl_if_ != NULL);

    gpio_if_ = audio_codec_new_gpio();
    assert(gpio_if_ != NULL);

    es8311_codec_cfg_t es8311_cfg = {};
    es8311_cfg.ctrl_if = ctrl_if_;
    es8311_cfg.gpio_if = gpio_if_;
    es8311_cfg.codec_mode = ESP_CODEC_DEV_WORK_MODE_BOTH;
    es8311_cfg.pa_pin = pa_pin;
    es8311_cfg.use_mclk = use_mclk;
    es8311_cfg.hw_gain.pa_voltage = 5.0;
    es8311_cfg.hw_gain.codec_dac_voltage = 3.3;
    es8311_cfg.pa_reverted = pa_inverted_;
    codec_if_ = es8311_codec_new(&es8311_cfg);

    if (codec_if_ == nullptr) {
        ESP_LOGE(TAG, "Failed to create Es8311AudioCodec");
    } else {
        ESP_LOGI(TAG, "Es8311AudioCodec initialized");
    }
}

Es8311AudioCodec::~Es8311AudioCodec() {
    esp_codec_dev_delete(dev_);

    audio_codec_delete_codec_if(codec_if_);
    audio_codec_delete_ctrl_if(ctrl_if_);
    audio_codec_delete_gpio_if(gpio_if_);
    audio_codec_delete_data_if(data_if_);
}

void Es8311AudioCodec::UpdateDeviceState() {
    if ((input_enabled_ || output_enabled_) && dev_ == nullptr) {
        esp_codec_dev_cfg_t dev_cfg = {
            .dev_type = ESP_CODEC_DEV_TYPE_IN_OUT,
            .codec_if = codec_if_,
            .data_if = data_if_,
        };
        dev_ = esp_codec_dev_new(&dev_cfg);
        assert(dev_ != NULL);

        esp_codec_dev_sample_info_t fs = {
            .bits_per_sample = 16,
            .channel = 1,
            .channel_mask = 0,
            .sample_rate = (uint32_t)input_sample_rate_,
            .mclk_multiple = 0,
        };
        ESP_ERROR_CHECK(esp_codec_dev_open(dev_, &fs));
        ESP_ERROR_CHECK(esp_codec_dev_set_in_gain(dev_, input_gain_));
        ESP_ERROR_CHECK(esp_codec_dev_set_out_vol(dev_, output_volume_));
    } else if (!input_enabled_ && !output_enabled_ && dev_ != nullptr) {
        esp_codec_dev_close(dev_);
        dev_ = nullptr;
    }
    if (pa_pin_ != GPIO_NUM_NC) {
        int level = output_enabled_ ? 1 : 0;
        gpio_set_level(pa_pin_, pa_inverted_ ? !level : level);
    }
}

void Es8311AudioCodec::CreateDuplexChannels(gpio_num_t mclk, gpio_num_t bclk, gpio_num_t ws, gpio_num_t dout, gpio_num_t din) {
    assert(input_sample_rate_ == output_sample_rate_);

    i2s_chan_config_t chan_cfg = {
        .id = I2S_NUM_0,
        .role = I2S_ROLE_MASTER,
        .dma_desc_num = AUDIO_CODEC_DMA_DESC_NUM,
        .dma_frame_num = AUDIO_CODEC_DMA_FRAME_NUM,
        .auto_clear_after_cb = true,
        .auto_clear_before_cb = false,
        .intr_priority = 0,
    };
    ESP_ERROR_CHECK(i2s_new_channel(&chan_cfg, &tx_handle_, &rx_handle_));

    i2s_std_config_t std_cfg = {
        .clk_cfg = {
            .sample_rate_hz = (uint32_t)output_sample_rate_,
            .clk_src = I2S_CLK_SRC_DEFAULT,
            .mclk_multiple = I2S_MCLK_MULTIPLE_256,
			#ifdef   I2S_HW_VERSION_2    
				.ext_clk_freq_hz = 0,
			#endif
        },
        .slot_cfg = {
            .data_bit_width = I2S_DATA_BIT_WIDTH_16BIT,
            .slot_bit_width = I2S_SLOT_BIT_WIDTH_AUTO,
            .slot_mode = I2S_SLOT_MODE_STEREO,
            .slot_mask = I2S_STD_SLOT_BOTH,
            .ws_width = I2S_DATA_BIT_WIDTH_16BIT,
            .ws_pol = false,
            .bit_shift = true,
            #ifdef   I2S_HW_VERSION_2   
                .left_align = true,
                .big_endian = false,
                .bit_order_lsb = false
            #endif
        },
        .gpio_cfg = {
            .mclk = mclk,
            .bclk = bclk,
            .ws = ws,
            .dout = dout,
            .din = din,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false
            }
        }
    };

    ESP_ERROR_CHECK(i2s_channel_init_std_mode(tx_handle_, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(rx_handle_, &std_cfg));
    ESP_ERROR_CHECK(i2s_channel_enable(tx_handle_));
    ESP_ERROR_CHECK(i2s_channel_enable(rx_handle_));
    ESP_LOGI(TAG, "Duplex channels created");
}

void Es8311AudioCodec::SetOutputVolume(int volume) {
    std::lock_guard<std::mutex> lock(data_if_mutex_);
    if (dev_ != nullptr) {
        ESP_ERROR_CHECK(esp_codec_dev_set_out_vol(dev_, volume));
    }
    AudioCodec::SetOutputVolume(volume);
}

void Es8311AudioCodec::EnableInput(bool enable) {
    std::lock_guard<std::mutex> lock(data_if_mutex_);
    if (codec_if_ == nullptr) {
        return;
    }
    if (enable == input_enabled_) {
        return;
    }
    if (!enable) {
        ResetReference();
    }
    AudioCodec::EnableInput(enable);
    UpdateDeviceState();
}

void Es8311AudioCodec::EnableOutput(bool enable) {
    std::lock_guard<std::mutex> lock(data_if_mutex_);
    if (codec_if_ == nullptr) {
        return;
    }
    if (enable == output_enabled_) {
        return;
    }
    if (!enable) {
        ResetReference();
    }
    AudioCodec::EnableOutput(enable);
    UpdateDeviceState();
}

void Es8311AudioCodec::ResetReference() {
    std::lock_guard<std::mutex> lock(ref_mutex_);
    ref_read_pos_ = 0;
    ref_write_pos_ = 0;
    ref_count_ = 0;
    ref_empty_reads_ = 0;
    ref_primed_ = false;
}

void Es8311AudioCodec::PushReferenceZerosLocked(size_t count) {
    const size_t cap = ref_buffer_.size();
    if (cap == 0 || count == 0) {
        return;
    }
    if (count >= cap) {
        std::fill(ref_buffer_.begin(), ref_buffer_.end(), 0);
        ref_read_pos_ = 0;
        ref_write_pos_ = 0;
        ref_count_ = cap;
        return;
    }
    if (ref_count_ + count > cap) {
        const size_t drop = (ref_count_ + count) - cap;
        ref_read_pos_ = (ref_read_pos_ + drop) % cap;
        ref_count_ -= drop;
    }
    const size_t first = std::min(count, cap - ref_write_pos_);
    std::fill_n(ref_buffer_.data() + ref_write_pos_, first, 0);
    if (count > first) {
        std::fill_n(ref_buffer_.data(), count - first, 0);
    }
    ref_write_pos_ = (ref_write_pos_ + count) % cap;
    ref_count_ += count;
}

void Es8311AudioCodec::PushReferenceSamplesLocked(const int16_t* data, size_t count) {
    const size_t cap = ref_buffer_.size();
    if (cap == 0 || data == nullptr || count == 0) {
        return;
    }
    if (count >= cap) {
        const int16_t* tail = data + (count - cap);
        std::memcpy(ref_buffer_.data(), tail, cap * sizeof(int16_t));
        ref_read_pos_ = 0;
        ref_write_pos_ = 0;
        ref_count_ = cap;
        return;
    }
    if (ref_count_ + count > cap) {
        const size_t drop = (ref_count_ + count) - cap;
        ref_read_pos_ = (ref_read_pos_ + drop) % cap;
        ref_count_ -= drop;
    }
    const size_t first = std::min(count, cap - ref_write_pos_);
    std::memcpy(ref_buffer_.data() + ref_write_pos_, data, first * sizeof(int16_t));
    if (count > first) {
        std::memcpy(ref_buffer_.data(), data + first, (count - first) * sizeof(int16_t));
    }
    ref_write_pos_ = (ref_write_pos_ + count) % cap;
    ref_count_ += count;
}

int Es8311AudioCodec::Read(int16_t* dest, int samples) {
    if (input_enabled_) {
        if (!input_reference_) {
            // 单声道模式：直接读麦克风
            ReadMicWithDiag(dev_, dest, samples, input_channels_);
        } else {
            // 双声道模式（麦克风 + 软件回采参考）
            const int mic_samples = samples / input_channels_;
            if (static_cast<int>(mic_scratch_.size()) != mic_samples) {
                mic_scratch_.resize(mic_samples);
            }

            // 读麦克风单声道数据
            ReadMicWithDiag(dev_, mic_scratch_.data(), mic_samples, input_channels_);

            // 交织：dest[0]=mic, dest[1]=ref, ...；无播报或欠载时参考通道严格补 0，绝不读旧残留
            std::lock_guard<std::mutex> lock(ref_mutex_);
            const size_t cap = ref_buffer_.size();
            const bool can_read_ref = output_enabled_ && cap > 0;
            int j = 0;
            int i = 0;
            if (!can_read_ref || ref_count_ == 0) {
                while (j < mic_samples) {
                    dest[i++] = mic_scratch_[j++];
                    dest[i++] = 0;
                }
                if (ref_primed_) {
                    ref_empty_reads_++;
                    // 连续约 100ms 无播报样本时复位起播状态，保证下一轮重新按前置延迟对齐
                    if (ref_empty_reads_ >= 10) {
                        ref_read_pos_ = 0;
                        ref_write_pos_ = 0;
                        ref_count_ = 0;
                        ref_empty_reads_ = 0;
                        ref_primed_ = false;
                    }
                }
            } else {
                ref_empty_reads_ = 0;
                while (j < mic_samples) {
                    dest[i++] = mic_scratch_[j++];
                    if (ref_count_ > 0) {
                        dest[i++] = ref_buffer_[ref_read_pos_];
                        ref_read_pos_ = (ref_read_pos_ + 1) % cap;
                        ref_count_--;
                    } else {
                        dest[i++] = 0;
                    }
                }
            }
        }
    }
    return samples;
}

int Es8311AudioCodec::Write(const int16_t* data, int samples) {
    if (output_enabled_) {
        ESP_ERROR_CHECK_WITHOUT_ABORT(esp_codec_dev_write(dev_, (void*)data, samples * sizeof(int16_t)));

        // 如果启用软件回采，线程安全地缓存播放数据并在起播时垫入对齐零样本
        if (input_reference_ && input_enabled_ && samples > 0) {
            std::lock_guard<std::mutex> lock(ref_mutex_);
            if (!ref_primed_) {
                const size_t prefill = static_cast<size_t>(output_sample_rate_) * ES8311_AEC_REF_PREFILL_MS / 1000;
                PushReferenceZerosLocked(prefill);
                ref_primed_ = true;
            }
            PushReferenceSamplesLocked(data, static_cast<size_t>(samples));
            ref_empty_reads_ = 0;
        }
    }
    return samples;
}