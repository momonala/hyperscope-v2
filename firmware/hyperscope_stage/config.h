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

// Carrier PCB rev C pin map (hardware/pcb/generate.py is the source of truth).
// Driver signals sit on the DevKit's 3V3-side row in module-header order. With the
// USB-C out of the left board edge that row is the one nearest the bottom edge, so
// the traces pass under the DevKit. GPIO 5 is a strapping pin sampled only at reset.
constexpr uint8_t PIN_X_STEP = 5;
constexpr uint8_t PIN_X_DIR = 18;
constexpr uint8_t PIN_Y_STEP = 19;
constexpr uint8_t PIN_Y_DIR = 21;
constexpr uint8_t PIN_EN = 4;  // shared by both drivers, active low

// The carrier PCB routes each driver's DIAG pin here
// through 1 kOhm. Unused until the knob hard stops are measured; configure as
// INPUT_PULLDOWN so a module with DIAG snipped reads as "no stall".
constexpr uint8_t PIN_X_DIAG = 13;
constexpr uint8_t PIN_Y_DIAG = 22;

// Blue "motor active" LEDs beside each motor terminal (PCB rev C), through 100 Ohm.
constexpr uint8_t PIN_X_LED = 32;
constexpr uint8_t PIN_Y_LED = 23;

constexpr uint8_t PIN_TMC_RX = 17;
constexpr uint8_t PIN_TMC_TX = 16;   // through 1 kOhm onto the shared PDN_UART line
constexpr uint8_t TMC_ADDR_X = 0b00;  // MS1 and MS2 jumpered to GND
constexpr uint8_t TMC_ADDR_Y = 0b01;  // MS1 jumpered to VIO, MS2 to GND
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
