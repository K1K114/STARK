#ifndef STEPPER_DRIVER_H
#define STEPPER_DRIVER_H

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
} StepperDriver;

bool Stepper_Init(
    StepperDriver *driver,
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

bool Stepper_Begin(StepperDriver *driver, uint32_t uart_baud);

void Stepper_Enable(StepperDriver *driver);
void Stepper_Disable(StepperDriver *driver);

void Stepper_SetDirection(StepperDriver *driver, bool clockwise);
void Stepper_SetPulseWidthUs(StepperDriver *driver, uint32_t pulse_width_us);

void Stepper_Pulse(StepperDriver *driver);
void Stepper_Step(StepperDriver *driver, uint32_t steps, bool clockwise);

void Stepper_StepAtRPM(StepperDriver *driver, uint32_t steps, bool clockwise, float rpm);
void Stepper_MoveRevolutions(StepperDriver *driver, float revolutions, bool clockwise);

uint8_t Stepper_TestConnection(StepperDriver *driver);

#endif
