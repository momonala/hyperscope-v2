// Hardware configuration for the hyperscope XY stage controller.
// ESP32-WROOM-32 DevKit driving BIGTREETECH TMC2209 modules in UART mode.
// Mirrors docs/hardware.md.
#pragma once

// MVPower NEMA 17, 1.5 A/phase (peak), 1.8 deg. 1.5 A peak is ~1060 mA RMS,
// so 1000 mA runs the motor at its rating. The knobs occasionally bind, and
// 600 mA was not enough to push through. The BTT TMC2209 modules have no fan
// and are comfortable to ~1.2 A RMS; the 12 V supply draw stays under 2 A.
constexpr uint16_t MOTOR_RMS_CURRENT_MA = 1000;
// Standstill current as a fraction of run current. A knob needs little holding
// torque, and lower hold current is quieter at rest.
constexpr float MOTOR_HOLD_FRACTION = 0.25f;
// StealthChop PWM frequency code: 0 = 23 kHz, 1 = 35 kHz, 2 = 47 kHz, 3 = 59 kHz.
constexpr uint8_t STEALTHCHOP_PWM_FREQ = 2;
constexpr uint16_t MICROSTEPS = 16;  // 3200 microsteps per knob revolution
constexpr float TMC_R_SENSE = 0.11f;

constexpr uint8_t PIN_X_STEP = 17;
constexpr uint8_t PIN_X_DIR = 25;  // left column: the right-hand column is full
constexpr uint8_t PIN_Y_STEP = 23;
constexpr uint8_t PIN_Y_DIR = 5;  // strapping pin, but only sampled at reset and DIR is harmless high
constexpr uint8_t PIN_EN = 22;  // shared by both drivers, active low

constexpr uint8_t PIN_TMC_RX = 21;
constexpr uint8_t PIN_TMC_TX = 19;   // through 1 kOhm onto the shared PDN_UART line
constexpr uint8_t TMC_ADDR_X = 0b00;  // MS1 and MS2 open
constexpr uint8_t TMC_ADDR_Y = 0b01;  // MS1 tied to VIO
constexpr uint32_t TMC_BAUD = 115200;

// Joystick, powered from 3V3 and never 5 V because these are ADC inputs.
// PIN_JOY_X is whichever input drives the X motor, which need not be the pin the
// module labels VRX once it is mounted.
constexpr uint8_t PIN_JOY_X = 35;
constexpr uint8_t PIN_JOY_Y = 34;
constexpr uint8_t PIN_JOY_SW = 33;  // to GND when pressed, internal pull-up
constexpr int JOY_ADC_MAX = 4095;
constexpr int JOY_DEADZONE = 120;
constexpr int JOY_CURVE_EXPONENT = 3;        // higher spends more of the throw at low speed
constexpr int JOY_CALIBRATION_SAMPLES = 64;  // these sticks do not rest at mid-scale
constexpr bool JOY_INVERT_X = false;
constexpr bool JOY_INVERT_Y = false;

// False leaves the motors free after a reset, which is safer against a supply
// whose current limit you are unsure of.
constexpr bool ENABLE_DRIVERS_AT_BOOT = true;
// Energising the motors within a few ms of writing the driver registers resets
// both chips to their pin defaults; 50 ms is enough, this leaves margin.
constexpr uint32_t DRIVER_ENABLE_SETTLE_MS = 100;
constexpr uint32_t DRIVER_CHECK_INTERVAL_MS = 1000;  // re-apply settings to a driver that has reset

// Motion, in microsteps/s and microsteps/s^2.
constexpr uint32_t DEFAULT_SPEED_HZ = 2700;
constexpr uint32_t DEFAULT_ACCEL = 8000;
constexpr uint32_t JOG_SPEED_COARSE_HZ = 4000;
constexpr uint32_t JOG_SPEED_FINE_HZ = 400;
constexpr uint32_t JOG_ACCEL = 80000;  // jogging needs a far harder ramp than a serial move

constexpr uint32_t HOST_BAUD = 115200;
constexpr uint16_t SERIAL_LINE_MAX = 120;

constexpr uint32_t JOY_POLL_INTERVAL_MS = 20;
constexpr uint32_t JOY_BUTTON_DEBOUNCE_MS = 200;
