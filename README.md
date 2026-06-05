# IoT-Based Classroom Energy Management System

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Flask](https://img.shields.io/badge/Flask-3.0-green)
![Docker](https://img.shields.io/badge/Docker-Containerized-blue)
![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-orange)
![SQLite](https://img.shields.io/badge/Database-SQLite-lightgrey)
![YOLOv8](https://img.shields.io/badge/AI-YOLOv8-red)
![Raspberry Pi](https://img.shields.io/badge/Platform-Raspberry%20Pi-darkgreen)

## Overview

The **IoT-Based Classroom Energy Management System** is an intelligent smart-building platform designed to optimize classroom energy consumption through IoT automation, AI-powered occupancy detection, predictive HVAC control, weather-aware ventilation, and automated scheduling.

The system combines edge computing devices, real-time sensors, MQTT communication, machine learning, and centralized management to reduce energy waste while maintaining occupant comfort.

---

# Repository Organization

The project is divided into two major components:

## Central Management Platform

Responsible for:

* Web dashboard
* Database management
* Classroom scheduling
* Analytics and reporting
* Weather integration
* Telegram notifications
* MQTT coordination
* Energy efficiency monitoring

## Edge IoT Node

Responsible for:

* Temperature sensing
* Motion detection
* AI occupancy detection
* HVAC control
* Lighting automation
* Ventilation control
* Real-time classroom monitoring

The Central platform communicates with Edge devices through MQTT, enabling real-time monitoring and intelligent energy optimization.

---

# Features

## Smart Monitoring

* Real-time temperature monitoring
* Motion detection using PIR sensors
* Occupancy estimation using AI camera analytics
* Historical sensor data collection
* Classroom status monitoring

## Intelligent Energy Optimization

* Predictive HVAC control
* Automatic AC pre-cooling before scheduled classes
* Weather-aware ventilation recommendations
* Occupancy-based lighting automation
* Adaptive temperature thresholds
* Duty-cycle protection for HVAC systems

## AI Occupancy Detection

* YOLOv8-based people detection
* Automatic occupancy counting
* Camera duty-cycling for power efficiency
* Sensor-failure fallback mechanisms

## Classroom Management

* Automated classroom assignment
* Capacity-aware scheduling
* Equipment-aware room selection
* Conflict detection and prevention

## Analytics & Reporting

* Energy efficiency scoring
* Historical temperature trends
* Occupancy analytics
* Classroom ranking system
* Performance visualization dashboards

## Remote Management

* Web dashboard
* Telegram bot integration
* Real-time alerts
* Manual override controls
* System health monitoring

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

| Category             | Technology                    |
| -------------------- | ----------------------------- |
| Backend              | Python                        |
| Web Framework        | Flask                         |
| Messaging Protocol   | MQTT                          |
| MQTT Broker          | Eclipse Mosquitto             |
| Database             | SQLite                        |
| AI & Computer Vision | YOLOv8, OpenCV                |
| Frontend             | HTML, Bootstrap 5, JavaScript |
| Data Visualization   | Chart.js                      |
| Notifications        | Telegram Bot API              |
| Weather Integration  | OpenWeatherMap API            |
| Containerization     | Docker                        |
| Orchestration        | Docker Compose                |
| Edge Hardware        | Raspberry Pi                  |

---

# Project Structure

```text
IoT-Based-Classroom-Energy-Management-System/

├── Central/
│   ├── app.py
│   ├── db_adaptor.py
│   ├── prediction_service.py
│   ├── statistics_service.py
│   ├── weather_service.py
│   ├── telegram_dashboard.py
│   ├── thermal_modeler.py
│   ├── room_selector.py
│   │
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── charts.html
│   │   ├── classrooms.html
│   │   ├── control.html
│   │   └── schedule.html
│   │
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── mosquitto.conf
│   └── requirements.txt
│
├── Edge/
│   ├── device_connector.py
│   ├── control_module.py
│   ├── camera_module.py
│   │
│   ├── Dockerfile.light
│   ├── Dockerfile.rpi
│   ├── docker-compose.yml
│   ├── requirements.light.txt
│   └── requirements.rpi.txt
│
├── README.md
└── .gitignore
```

---

# Quick Start

## Prerequisites

### Software

* Docker
* Docker Compose

Verify installation:

```bash
docker --version
docker compose version
```

### Hardware (Optional)

* Raspberry Pi 4 / Raspberry Pi 5
* PIR Motion Sensor
* DS18B20 Temperature Sensor
* USB Camera
* MQTT Broker

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

## View Logs

```bash
docker compose logs -f
```

### Individual Services

```bash
docker compose logs -f sensors
docker compose logs -f controller
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

## Discovery Topics

```text
system/discover
system/discover/<room>/response
```

---

# Database Design

### sensor_history

Stores:

* Temperature
* Motion status
* Occupancy count
* AC state
* Lighting state
* Operating mode

### classroom_metadata

Stores:

* Room capacity
* Available equipment
* Thermal characteristics
* Efficiency metrics

### course_schedule

Stores:

* Scheduled courses
* Room assignments
* Recurring sessions
* Classroom requirements

### control_logs

Stores:

* Manual commands
* Automated actions
* Acknowledgements
* Execution history

### efficiency_history

Stores:

* Historical efficiency scores

### weather_history

Stores:

* External weather data

---

# Results

The system demonstrates:

* Automated classroom energy optimization
* Occupancy-aware HVAC control
* Weather-aware ventilation recommendations
* AI-powered occupancy estimation
* Centralized monitoring and management
* Reduced unnecessary energy consumption

---

# Screenshots

## Dashboard

*Add dashboard screenshot here*

## Analytics

*Add analytics screenshot here*

## Control Panel

*Add control panel screenshot here*

---

# Future Improvements

* Energy consumption forecasting
* Mobile application
* Multi-building deployment
* Reinforcement learning HVAC optimization
* BACnet integration
* Smart grid connectivity
* Renewable energy integration
* Cloud analytics dashboard

---

# Authors

This project was developed by:

* **Ehsan Nikpey**
* **Seyed Erfan Ghoreishi**
* **Alireza Nourishad**
* **Shabnam Amouie**

---

# License

This project was developed for educational and research purposes.

---

# Acknowledgments

* Flask
* Eclipse Mosquitto
* OpenWeatherMap
* YOLOv8
* OpenCV
* Bootstrap
* Chart.js
* Docker
* Raspberry Pi Foundation
