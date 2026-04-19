#ifndef TMC2209_DRIVER_H
#define TMC2209_DRIVER_H

#include <stdbool.h>
#include <stdint.h>

class HardwareSerial;
class TMC2209Stepper;

typedef struct {
    int step_pin;
    int dir_pin;
    int en_pin;
    int uart_tx_pin;
    int uart_rx_pin;
    uint8_t uart_address;
    bool dir_inverted;
    bool en_active_low;
    uint32_t pulse_width_us;
    uint32_t steps_per_rev;
    bool is_enabled;
    float r_sense;
    uint16_t run_current_ma;
    uint16_t microsteps;
    HardwareSerial *uart;
    TMC2209Stepper *tmc;
} TMC2209Driver;

bool TMC2209_Init(
    TMC2209Driver *driver,
    HardwareSerial *uart,
    int uart_rx_pin,
    int uart_tx_pin,
    uint8_t uart_address,
    int step_pin,
    int dir_pin,
    int en_pin,
    bool dir_inverted,
    bool en_active_low,
    uint32_t steps_per_rev,
    float r_sense,
    uint16_t run_current_ma,
    uint16_t microsteps
);

bool TMC2209_Begin(TMC2209Driver *driver, uint32_t uart_baud);

void TMC2209_Enable(TMC2209Driver *driver);
void TMC2209_Disable(TMC2209Driver *driver);

void TMC2209_SetDirection(TMC2209Driver *driver, bool clockwise);
void TMC2209_SetPulseWidthUs(TMC2209Driver *driver, uint32_t pulse_width_us);
void TMC2209_SetStepLevel(TMC2209Driver *driver, bool level_high);
void TMC2209_Pulse(TMC2209Driver *driver);

uint8_t TMC2209_TestConnection(TMC2209Driver *driver);

#endif
