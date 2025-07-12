# DWD Precipitation

This custom component for Home Assistant provides detailed radar precipitation forecasts and historical precipitation values from the past for Germany.


The data is derived from the radar based *Radvor* and *Radolan* products provided by the DWD (Deutscher Wetterdienst) allowing you to track rain events at your precise location. 

Ideal for automations and warnings of severe precipitation events.

## Entities

Entitiy | Description | Data source |
| ---- | ---- | ---- |
| `Precipitation +2 hours`| Calibrated precipitation forecast [mm/h] for the timespan +60 minutes to +120 minutes | Radvor RW |


