# IoT-Based Classroom Energy Management System

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue)
![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-orange)
![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey)
![YOLOv8](https://img.shields.io/badge/AI-YOLOv8-red)
![Platform](https://img.shields.io/badge/Platform-Raspberry%20Pi-darkgreen)

## Overview

The **IoT-Based Classroom Energy Management System** is an intelligent smart-building platform designed to optimize classroom energy consumption through IoT automation, AI-powered occupancy detection, predictive HVAC control, weather-aware ventilation, and automated scheduling.

The system combines edge computing devices, real-time sensors, MQTT communication, machine learning, and centralized management to reduce energy waste while maintaining occupant comfort.

---

## Features

### Smart Monitoring
- Real-time temperature monitoring
- Motion detection using PIR sensors
- Occupancy estimation using AI camera analytics
- Historical sensor data collection
- Classroom status monitoring

### Intelligent Energy Optimization
- Predictive HVAC control
- Automatic AC pre-cooling before scheduled classes
- Weather-aware ventilation recommendations
- Occupancy-based lighting automation
- Adaptive temperature thresholds
- Duty-cycle protection for HVAC systems

### AI Occupancy Detection
- YOLOv8-based people detection
- Automatic occupancy counting
- Camera duty-cycling for power efficiency
- Sensor-failure fallback mechanisms

### Classroom Management
- Automated classroom assignment
- Capacity-aware scheduling
- Equipment-aware room selection
- Conflict detection and prevention

### Analytics & Reporting
- Energy efficiency scoring
- Historical temperature trends
- Occupancy analytics
- Classroom ranking system
- Performance visualization dashboards

### Remote Management
- Web dashboard
- Telegram bot integration
- Real-time alerts
- Manual override controls
- System health monitoring

---

# System Architecture

```text
                        ┌─────────────────────┐
                        │   Web Dashboard     │
                        │      Flask UI       │
                        └──────────┬──────────┘
                                   │
                                   ▼

                        ┌─────────────────────┐
                        │     SQLite DB       │
                        └──────────┬──────────┘
                                   │

        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼

 Prediction Service       Statistics Service        Weather Service

                                   │
                                   ▼

                        ┌─────────────────────┐
                        │     MQTT Broker     │
                        │     Mosquitto       │
                        └──────────┬──────────┘
                                   │

           ┌───────────────────────┼───────────────────────┐
           ▼                       ▼                       ▼

    Device Connector       Control Module        Camera Module
    (Sensors)              (Automation)          (YOLOv8)

           │                       │                       │
           └───────────────────────┴───────────────────────┘

                        Smart Classroom
```

---

# Technology Stack

| Category | Technology |
|-----------|------------|
| Backend | Python |
| Web Framework | Flask |
| Messaging | MQTT |
| Broker | Eclipse Mosquitto |
| Database | SQLite |
| AI Vision | YOLOv8 |
| Computer Vision | OpenCV |
| Frontend | Bootstrap 5 |
| Analytics | Chart.js |
| Notifications | Telegram Bot API |
| Weather API | OpenWeatherMap |
| Containerization | Docker |
| Orchestration | Docker Compose |

---

# Project Structure

```text
IoT-Based-Classroom-Energy-Management-System/

├── app.py
├── db_adaptor.py
├── prediction_service.py
├── statistics_service.py
├── weather_service.py
├── telegram_dashboard.py
├── thermal_modeler.py
├── room_selector.py
│
├── device_connector.py
├── control_module.py
├── camera_module.py
│
├── templates/
│   ├── index.html
│   ├── charts.html
│   ├── classrooms.html
│   ├── control.html
│   ├── schedule.html
│   └── base.html
│
├── Dockerfile
├── Dockerfile.light
├── Dockerfile.rpi
├── docker-compose.yml
│
├── mosquitto.conf
├── requirements.txt
├── requirements.light.txt
├── requirements.rpi.txt
│
└── classroom_data.db
```

---

# Quick Start

## Prerequisites

### Software

- Docker
- Docker Compose

Verify installation:

```bash
docker --version
docker compose version
```

### Hardware (Optional)

- Raspberry Pi 4 / Raspberry Pi 5
- PIR Motion Sensor
- DS18B20 Temperature Sensor
- USB Camera
- MQTT Broker

---

# Configure Environment

Create a `.env` file:

```env
MQTT_BROKER_HOST=127.0.0.1

ROOM_ID=classroom001

HAS_CAMERA=true

TEMP_MODE=normal

DEFAULT_AC_PRECOOL_TEMP=21

THRESHOLD_BASE=21.0
HOLDUP_BAND=1.5

MOTION_START_HOUR=8
MOTION_END_HOUR=18

CAMERA_ACTIVE_SECONDS=30
CAMERA_SLEEP_SECONDS=60

MANUAL_MODE_HOLD_SECONDS=60
```

---

# Docker Deployment

## Build Containers

```bash
docker compose build
```

## Start Services

```bash
docker compose up -d
```

## Verify Containers

```bash
docker ps
```

Expected services:

```text
sensors
controller
camera
```

## View Logs

All services:

```bash
docker compose logs -f
```

Sensors:

```bash
docker compose logs -f sensors
```

Controller:

```bash
docker compose logs -f controller
```

Camera:

```bash
docker compose logs -f camera
```

## Stop Services

```bash
docker compose down
```

## Restart Services

```bash
docker compose restart
```

## Rebuild After Changes

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

# Raspberry Pi Deployment

The edge node is designed to run on Raspberry Pi devices.

### Lightweight Edge Build

```bash
docker build -f Dockerfile.light -t smart-classroom-edge .
```

### AI Camera Build

```bash
docker build -f Dockerfile.rpi -t smart-classroom-ai .
```

Supported hardware:

- PIR Motion Sensor
- DS18B20 Temperature Sensor
- USB Camera
- MQTT Broker

---

# MQTT Topics

## Sensor Data

```text
<classroom>/sensors
```

Example:

```text
classroom001/sensors
```

Payload:

```json
{
  "motion": 1,
  "temperature": 24.5
}
```

---

## Occupancy Detection

```text
<classroom>/camera/occupancy
```

Payload:

```json
{
  "occupancy_count": 12
}
```

---

## AC Control

```text
<classroom>/ac/control
```

Commands:

```text
ON
OFF
LOW
MEDIUM
HIGH
```

---

## AC Precooling

```text
<classroom>/ac/precool
```

Payload:

```json
{
  "target_temp": 21,
  "duration_minutes": 15,
  "source": "schedule"
}
```

---

## Ventilation Control

```text
<classroom>/ventilation/suggest
```

Payload:

```json
{
  "action": "activate"
}
```

---

## Discovery Topics

```text
system/discover
system/discover/<room>/response
```

---

# Database Design

The system automatically creates and manages the following tables:

### sensor_history

Stores:

- Temperature
- Motion status
- Occupancy count
- AC state
- Lighting state
- Operating mode

### classroom_metadata

Stores:

- Room capacity
- Available equipment
- Thermal characteristics
- Efficiency metrics

### course_schedule

Stores:

- Scheduled courses
- Room assignments
- Recurring sessions
- Classroom requirements

### control_logs

Stores:

- Manual commands
- Automated actions
- Acknowledgements
- Execution history

### efficiency_history

Stores:

- Historical efficiency scores

### weather_history

Stores:

- External weather data

---

# Research Contribution

This project demonstrates how IoT devices, AI-based occupancy detection, predictive control strategies, and weather-aware automation can be integrated into a unified smart-building platform.

The system aims to:

- Reduce unnecessary HVAC operation
- Reduce lighting energy consumption
- Improve classroom utilization
- Maintain thermal comfort
- Support data-driven facility management

---

# Future Improvements

- Energy consumption forecasting
- Mobile application
- Multi-building deployment
- Reinforcement learning HVAC optimization
- BACnet integration
- Smart grid connectivity
- Renewable energy integration
- Cloud analytics dashboard

---

# License

This project was developed for educational and research purposes.

---

# Authors

Ehsan Nikpey
Seyed Erfan Ghoreishi 
Alireza Nourishad 
Shabnam Amouie

---

# Acknowledgments

- Flask
- Eclipse Mosquitto
- OpenWeatherMap
- YOLOv8
- OpenCV
- Bootstrap
- Chart.js
- Docker
- Raspberry Pi Foundation
