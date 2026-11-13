// Debounced push button with click and long-press detection. No Arduino dependency.
#pragma once

#include <stdint.h>

enum class ButtonEvent {
  None,
  Down,       // debounced press
  Click,      // released before the long-press time
  LongPress,  // held for the long-press time; reported once, no Click follows
};

class Button {
 public:
  explicit Button(uint32_t debounce_ms = 30, uint32_t long_press_ms = 2000)
      : debounce_ms_(debounce_ms), long_press_ms_(long_press_ms) {}

  // Call often (every few ms) with the raw contact state.
  ButtonEvent update(bool raw_pressed, uint32_t now_ms) {
    if (raw_pressed != raw_) {
      raw_ = raw_pressed;
      raw_changed_ms_ = now_ms;
    }
    if (pressed_ != raw_ && now_ms - raw_changed_ms_ >= debounce_ms_) {
      pressed_ = raw_;
      if (pressed_) {
        pressed_ms_ = now_ms;
        long_reported_ = false;
        return ButtonEvent::Down;
      }
      return long_reported_ ? ButtonEvent::None : ButtonEvent::Click;
    }
    if (pressed_ && !long_reported_ && now_ms - pressed_ms_ >= long_press_ms_) {
      long_reported_ = true;
      return ButtonEvent::LongPress;
    }
    return ButtonEvent::None;
  }

  bool pressed() const { return pressed_; }

 private:
  uint32_t debounce_ms_;
  uint32_t long_press_ms_;
  bool raw_ = false;
  bool pressed_ = false;
  bool long_reported_ = false;
  uint32_t raw_changed_ms_ = 0;
  uint32_t pressed_ms_ = 0;
};
