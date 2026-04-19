#ifndef DRV8825_DRIVER_H
#define DRV8825_DRIVER_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int step_pin;
    int dir_pin;
    int en_pin;
    bool dir_inverted;
    bool en_active_low;
    uint32_t pulse_width_us;
    bool is_enabled;
} DRV8825Driver;

bool DRV8825_Init(
    DRV8825Driver *driver,
    int step_pin,
    int dir_pin,
    int en_pin,
    bool dir_inverted,
    bool en_active_low
);

void DRV8825_Enable(DRV8825Driver *driver);
void DRV8825_Disable(DRV8825Driver *driver);

void DRV8825_SetDirection(DRV8825Driver *driver, bool clockwise);
void DRV8825_SetPulseWidthUs(DRV8825Driver *driver, uint32_t pulse_width_us);
void DRV8825_SetStepLevel(DRV8825Driver *driver, bool level_high);
void DRV8825_Pulse(DRV8825Driver *driver);

#endif
